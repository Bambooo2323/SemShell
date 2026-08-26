"""In-memory dispatcher from ControlRequests to public Kernel operations."""

from __future__ import annotations

import asyncio
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
    ReapProcess,
    ResolveImage,
    SpawnProcesses,
    UnregisterImage,
    WaitProcess,
)
from semshell.security.authority import Authority
from semshell.security.principal import Principal

MUTATING_OPERATION_TYPES = (
    SpawnProcesses,
    CancelProcess,
    ReapProcess,
    UnregisterImage,
)


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
        if not await session.dispatch(handle):
            self._record_reply(session, handle, await handle.wait_reply())
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
        handle = self._handles[key]
        self._record_reply(session, handle, await handle.wait_reply())
        handler = self._handlers.get(key)
        if handler is not None:
            handler.cancel()
        return True

    async def close_session(
        self, session: ControlSession, reason: str = "control session closed"
    ) -> None:
        """Close admission, interrupt observations, and release handler tasks."""

        related = [
            (key, handle, handle.is_replied)
            for key, handle in self._handles.items()
            if key[0] == session.session_id
        ]
        await session.close(reason)
        for key, handle, was_replied in related:
            if not was_replied:
                self._record_reply(session, handle, await handle.wait_reply())
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
        for key, _, _ in related:
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
                self._record_reply(session, handle, await handle.wait_reply())
            else:
                self._record_late(session, handle, error=error)
            return

        if await handle.succeed(value):
            self._record_reply(session, handle, await handle.wait_reply())
        else:
            self._record_late(session, handle, value=value)

    async def _execute_bounded_mutation(
        self, session: ControlSession, operation: Any
    ) -> Any:
        async with self._mutation_slots:
            return await self._execute(session, operation)

    async def _execute(self, session: ControlSession, operation: Any) -> Any:
        if isinstance(operation, ListImages):
            return self.kernel.list_images()
        if isinstance(operation, ResolveImage):
            return self.kernel.resolve_image(
                image=operation.image,
                capability=operation.capability,
                provider=operation.provider,
            )
        if isinstance(operation, UnregisterImage):
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
            return await self.kernel.reap(operation.pid)
        raise TypeError(f"unsupported external operation: {type(operation).__name__}")

    def _record_reply(
        self, session: ControlSession, handle: RequestHandle, reply: ControlReply
    ) -> None:
        outcomes = {
            ReplyStatus.SUCCEEDED: AuditOutcome.SUCCEEDED,
            ReplyStatus.REJECTED: AuditOutcome.REJECTED,
            ReplyStatus.INTERRUPTED: AuditOutcome.INTERRUPTED,
        }
        self._audit.append(
            ControlAuditRecord(
                session_id=session.session_id,
                request_id=handle.request_id,
                principal=session.context.principal,
                operation=handle.operation_name,
                outcome=outcomes[reply.status],
                error=reply.error,
            )
        )

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
        details = {} if error is not None else {"result": value}
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
