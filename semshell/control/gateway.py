"""In-memory dispatcher from ControlRequests to public Kernel operations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from semshell.control.audit import AuditOutcome, ControlAuditRecord
from semshell.control.error import ControlError, ControlErrorOrigin
from semshell.control.reply import ControlReply, ReplyStatus
from semshell.control.request import ControlRequest, RequestId
from semshell.control.session import ControlSession, RequestHandle, SessionId
from semshell.kernel.errors import (
    ApprovalRequired,
    InvalidAction,
    InvalidKernelState,
    KernelNotRunning,
    OperationDenied,
    ProcessNotFound,
)
from semshell.kernel.kernel import ProcessKernel
from semshell.kernel.operations import (
    CancelProcess,
    InspectProcess,
    InspectTree,
    ListImages,
    ListProcesses,
    ReapProcess,
    ResolveImage,
    SpawnProcesses,
    UnregisterImage,
    WaitProcess,
)
from semshell.security.authority import Authority, Permission
from semshell.security.principal import Principal

MUTATING_OPERATION_TYPES = (
    SpawnProcesses,
    CancelProcess,
    ReapProcess,
    UnregisterImage,
)

CONTROL_CANCEL = Permission("control.process.cancel")
CONTROL_REAP = Permission("control.process.reap")
CONTROL_CATALOG_UNREGISTER = Permission("control.catalog.unregister")


class ControlGateway:
    """Apply external requests without exposing transport or Kernel internals."""

    def __init__(self, kernel: ProcessKernel, *, max_mutations: int = 16) -> None:
        if max_mutations <= 0:
            raise ValueError("max_mutations must be positive")
        self.kernel = kernel
        self._mutation_slots = asyncio.Semaphore(max_mutations)
        self._handlers: dict[tuple[SessionId, RequestId], asyncio.Task[None]] = {}
        self._handles: dict[tuple[SessionId, RequestId], RequestHandle] = {}
        self._operation_tasks: set[asyncio.Task[Any]] = set()
        self._audit: list[ControlAuditRecord] = []

    def open_session(
        self,
        *,
        principal: Principal,
        authority: Authority,
        max_in_flight: int = 32,
    ) -> ControlSession:
        """Create one admitted in-memory control session."""

        return ControlSession(
            principal=principal,
            authority=authority,
            max_in_flight=max_in_flight,
        )

    def audit_records(self) -> tuple[ControlAuditRecord, ...]:
        """Return an immutable snapshot of in-memory audit records."""

        return tuple(self._audit)

    async def submit(
        self, session: ControlSession, request: ControlRequest
    ) -> RequestHandle:
        """Admit and dispatch one request, returning its one-shot handle."""

        handle = await session.admit(request)
        key = (session.session_id, request.request_id)
        self._handles[key] = handle
        handle.bind_reply_commit(
            lambda reply: self._prepare_reply_audit(session, handle, reply)
        )
        if not await session.dispatch(handle):
            return handle

        task = asyncio.create_task(self._run(session, handle))
        self._handlers[key] = task

        def discard(completed: asyncio.Task[None]) -> None:
            self._handlers.pop(key, None)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(discard)
        return handle

    async def interrupt(
        self,
        session: ControlSession,
        request_id: RequestId,
        reason: str = "request interrupted",
    ) -> bool:
        """Interrupt request observation without cancelling a Process target."""

        won = await session.interrupt(request_id, reason)
        if not won:
            return False
        key = (session.session_id, request_id)
        handler = self._handlers.get(key)
        if handler is not None:
            handler.cancel()
        return True

    async def close_session(
        self, session: ControlSession, reason: str = "control session closed"
    ) -> None:
        """Close admission, interrupt observations, and release handler tasks."""

        related = [
            (key, handle)
            for key, handle in self._handles.items()
            if key[0] == session.session_id
        ]
        await session.close(reason)
        for key, _ in related:
            handler = self._handlers.get(key)
            if handler is not None:
                handler.cancel()
        handlers = [
            handler
            for key, handler in self._handlers.items()
            if key[0] == session.session_id
        ]
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        for key, _ in related:
            self._handles.pop(key, None)

    async def _run(self, session: ControlSession, handle: RequestHandle) -> None:
        operation = handle.request.operation
        mutation_task: asyncio.Task[Any] | None = None
        try:
            if isinstance(operation, MUTATING_OPERATION_TYPES):
                mutation_task = asyncio.create_task(
                    self._execute_bounded_mutation(session, operation)
                )
                self._operation_tasks.add(mutation_task)
                mutation_task.add_done_callback(self._operation_tasks.discard)
                value = await asyncio.shield(mutation_task)
            else:
                value = await self._execute(session, operation)
        except asyncio.CancelledError:
            if mutation_task is not None:
                self._record_late_when_done(session, handle, mutation_task)
            return
        except Exception as exc:  # noqa: BLE001
            error = self._normalize_error(exc)
            if await handle.reject(error):
                return
            self._record_late(session, handle, error=error)
            return

        if await handle.succeed(value):
            return
        self._record_late(session, handle, value=value)

    async def _execute_bounded_mutation(
        self, session: ControlSession, operation: Any
    ) -> Any:
        async with self._mutation_slots:
            return await self._execute(session, operation)

    async def _execute(self, session: ControlSession, operation: Any) -> Any:
        if isinstance(operation, ListImages):
            return self.kernel.list_images()
        if isinstance(operation, ListProcesses):
            return self.kernel.list_processes()
        if isinstance(operation, ResolveImage):
            return self.kernel.resolve_image(
                image=operation.image,
                capability=operation.capability,
                provider=operation.provider,
            )
        if isinstance(operation, UnregisterImage):
            self._require_permission(session, CONTROL_CATALOG_UNREGISTER)
            return self.kernel.unregister_image(operation.reference)
        if isinstance(operation, SpawnProcesses):
            return await self.kernel.spawn_many(
                operation.specs,
                principal=session.context.principal,
                authority_ceiling=session.context.authority,
            )
        if isinstance(operation, WaitProcess):
            return await self.kernel.wait(operation.pid, timeout=operation.timeout)
        if isinstance(operation, CancelProcess):
            self._require_permission(session, CONTROL_CANCEL)
            return await self.kernel.cancel(
                operation.target_pid,
                mode=operation.mode,
                reason=operation.reason,
            )
        if isinstance(operation, InspectProcess):
            return self.kernel.inspect(operation.pid)
        if isinstance(operation, InspectTree):
            return self.kernel.tree(operation.pid)
        if isinstance(operation, ReapProcess):
            self._require_permission(session, CONTROL_REAP)
            return await self.kernel.reap(operation.pid)
        raise TypeError(f"unsupported external operation: {type(operation).__name__}")

    @staticmethod
    def _require_permission(
        session: ControlSession, permission: Permission
    ) -> None:
        if permission not in session.context.authority.permissions:
            raise OperationDenied(
                f"control operation requires {permission.capability}"
            )

    def _prepare_reply_audit(
        self, session: ControlSession, handle: RequestHandle, reply: ControlReply
    ) -> Callable[[], None]:
        """Build the terminal audit record before the reply is committed."""
        outcomes = {
            ReplyStatus.SUCCEEDED: AuditOutcome.SUCCEEDED,
            ReplyStatus.REJECTED: AuditOutcome.REJECTED,
            ReplyStatus.INTERRUPTED: AuditOutcome.INTERRUPTED,
        }
        details = self._operation_audit_details(
            handle.request.operation, value=reply.value
        )
        if reply.error is not None:
            details["policy_reason"] = reply.error.message
        elif isinstance(handle.request.operation, SpawnProcesses):
            details["policy_reason"] = "spawn admission policy accepted"
        elif isinstance(handle.request.operation, MUTATING_OPERATION_TYPES):
            details["policy_reason"] = "control administration authority accepted"
        record = ControlAuditRecord(
            session_id=session.session_id,
            request_id=handle.request_id,
            principal=session.context.principal,
            operation=handle.operation_name,
            outcome=outcomes[reply.status],
            error=reply.error,
            details=details,
        )
        return lambda: self._audit.append(record)

    @staticmethod
    def _operation_audit_details(
        operation: Any, *, value: Any = None
    ) -> dict[str, Any]:
        if isinstance(operation, CancelProcess):
            return {"target_pid": operation.target_pid, "mode": operation.mode.value}
        if isinstance(operation, ReapProcess):
            return {"target_pid": operation.pid}
        if isinstance(operation, UnregisterImage):
            return {"target_image": operation.reference}
        if isinstance(operation, SpawnProcesses):
            details = {
                "requested_authority": tuple(
                    tuple(
                        {
                            "capability": permission.capability,
                            "scope": permission.scope,
                        }
                        for permission in sorted(spec.requested_authority.permissions)
                    )
                    for spec in operation.specs
                )
            }
            if (
                isinstance(value, tuple)
                and value
                and all(isinstance(pid, int) for pid in value)
            ):
                details["created_pids"] = value
            return details
        return {}

    def _record_late_when_done(
        self,
        session: ControlSession,
        handle: RequestHandle,
        task: asyncio.Task[Any],
    ) -> None:
        def record(completed: asyncio.Task[Any]) -> None:
            if completed.cancelled():
                self._record_late(
                    session,
                    handle,
                    error=ControlError(
                        code="gateway.operation_cancelled",
                        message="shielded operation was cancelled",
                        origin=ControlErrorOrigin.GATEWAY,
                    ),
                )
                return
            error = completed.exception()
            if error is None:
                self._record_late(session, handle, value=completed.result())
            else:
                self._record_late(session, handle, error=self._normalize_error(error))

        task.add_done_callback(record)

    def _record_late(
        self,
        session: ControlSession,
        handle: RequestHandle,
        *,
        value: Any = None,
        error: ControlError | None = None,
    ) -> None:
        details = self._operation_audit_details(
            handle.request.operation, value=value
        )
        details["policy_reason"] = (
            error.message
            if error is not None
            else "spawn admission policy accepted"
            if isinstance(handle.request.operation, SpawnProcesses)
            else "control administration authority accepted"
        )
        self._audit.append(
            ControlAuditRecord(
                session_id=session.session_id,
                request_id=handle.request_id,
                principal=session.context.principal,
                operation=handle.operation_name,
                outcome=(
                    AuditOutcome.LATE_REJECTED
                    if error is not None
                    else AuditOutcome.LATE_SUCCEEDED
                ),
                error=error,
                details=details,
            )
        )

    @staticmethod
    def _normalize_error(exc: BaseException) -> ControlError:
        if isinstance(exc, asyncio.TimeoutError):
            return ControlError(
                code="gateway.timeout",
                message="control operation timed out",
                origin=ControlErrorOrigin.GATEWAY,
                retryable=True,
            )
        mappings: tuple[tuple[type[BaseException], str], ...] = (
            (KernelNotRunning, "kernel.not_running"),
            (ProcessNotFound, "kernel.process_not_found"),
            (InvalidKernelState, "kernel.invalid_state"),
            (InvalidAction, "kernel.invalid_action"),
            (ApprovalRequired, "policy.approval_required"),
            (OperationDenied, "policy.operation_denied"),
            (LookupError, "kernel.lookup_failed"),
            (ValueError, "kernel.invalid_argument"),
        )
        for error_type, code in mappings:
            if isinstance(exc, error_type):
                return ControlError(
                    code=code,
                    message=str(exc) or error_type.__name__,
                    origin=(
                        ControlErrorOrigin.POLICY
                        if isinstance(exc, OperationDenied)
                        else ControlErrorOrigin.KERNEL
                    ),
                    retryable=isinstance(exc, ApprovalRequired),
                )
        return ControlError(
            code="gateway.internal_error",
            message="unexpected control operation failure",
            origin=ControlErrorOrigin.GATEWAY,
        )
