"""Pure session and one-shot request state for the control protocol."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from semshell.control.error import (
    ControlError,
    ControlErrorOrigin,
    SessionProtocolError,
)
from semshell.control.reply import ControlReply, ReplyStatus
from semshell.control.request import PROTOCOL_VERSION, ControlRequest, RequestId
from semshell.security.authority import Authority
from semshell.security.principal import Principal


@dataclass(frozen=True, slots=True, order=True)
class SessionId:
    """Opaque identity unique within one live ControlGateway."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("session ID must not be empty")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ControlContext:
    """Immutable caller identity established during session admission."""

    session_id: SessionId
    principal: Principal
    authority: Authority
    audit_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "audit_metadata", MappingProxyType(dict(self.audit_metadata))
        )


class RequestState(StrEnum):
    """Externally observable lifecycle of one admitted request."""

    ADMITTED = "ADMITTED"
    DISPATCHED = "DISPATCHED"
    REPLIED = "REPLIED"


class SessionState(StrEnum):
    """Admission lifecycle of one control session."""

    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class RequestHandle:
    """Own the one-shot reply gate and interruption state for one request."""

    def __init__(self, request: ControlRequest) -> None:
        self.request = request
        self._state = RequestState.ADMITTED
        self._interrupted = False
        self._lock = asyncio.Lock()
        self._reply: asyncio.Future[ControlReply] = (
            asyncio.get_running_loop().create_future()
        )

    @property
    def request_id(self) -> RequestId:
        return self.request.request_id

    @property
    def operation_name(self) -> str:
        name = type(self.request.operation).__name__
        return name.removesuffix("Request")

    @property
    def state(self) -> RequestState:
        return self._state

    @property
    def interrupted(self) -> bool:
        return self._interrupted

    @property
    def is_replied(self) -> bool:
        return self._state is RequestState.REPLIED

    async def mark_dispatched(self) -> bool:
        """Move ADMITTED to DISPATCHED unless a terminal reply already won."""

        async with self._lock:
            if self._state is not RequestState.ADMITTED:
                return False
            self._state = RequestState.DISPATCHED
            return True

    async def succeed(
        self, value: Any = None, *, metadata: Mapping[str, Any] | None = None
    ) -> bool:
        """Attempt to commit the unique successful reply."""

        return await self._commit(
            ControlReply(
                request_id=self.request_id,
                operation=self.operation_name,
                status=ReplyStatus.SUCCEEDED,
                value=value,
                metadata=metadata or {},
            )
        )

    async def reject(self, error: ControlError) -> bool:
        """Attempt to commit the unique rejected reply."""

        return await self._commit(
            ControlReply(
                request_id=self.request_id,
                operation=self.operation_name,
                status=ReplyStatus.REJECTED,
                error=error,
            )
        )

    async def interrupt(self, reason: str = "request interrupted") -> bool:
        """Set interruption state and attempt to win the reply gate."""

        if not reason:
            raise ValueError("interruption reason must not be empty")
        async with self._lock:
            self._interrupted = True
            if self._state is RequestState.REPLIED:
                return False
            self._state = RequestState.REPLIED
            self._reply.set_result(
                ControlReply(
                    request_id=self.request_id,
                    operation=self.operation_name,
                    status=ReplyStatus.INTERRUPTED,
                    error=ControlError(
                        code="gateway.interrupted",
                        message=reason,
                        origin=ControlErrorOrigin.GATEWAY,
                        retryable=True,
                    ),
                )
            )
            return True

    async def wait_reply(self) -> ControlReply:
        """Wait for the already unique terminal reply without cancelling it."""

        return await asyncio.shield(self._reply)

    async def _commit(self, reply: ControlReply) -> bool:
        async with self._lock:
            if self._state is RequestState.REPLIED:
                return False
            self._state = RequestState.REPLIED
            self._reply.set_result(reply)
            return True


class ControlSession:
    """Own request identity, capacity, interruption, and explicit closure."""

    def __init__(
        self,
        *,
        principal: Principal,
        authority: Authority,
        session_id: SessionId | None = None,
        max_in_flight: int = 32,
        audit_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if max_in_flight <= 0:
            raise ValueError("max_in_flight must be positive")
        self.context = ControlContext(
            session_id=session_id or SessionId(str(uuid4())),
            principal=principal,
            authority=authority,
            audit_metadata=audit_metadata or {},
        )
        self.max_in_flight = max_in_flight
        self._state = SessionState.OPEN
        self._lock = asyncio.Lock()
        self._handles: dict[RequestId, RequestHandle] = {}

    @property
    def session_id(self) -> SessionId:
        return self.context.session_id

    @property
    def state(self) -> SessionState:
        return self._state

    async def admit(self, request: ControlRequest) -> RequestHandle:
        """Atomically reserve the RequestId and create its reply gate."""

        async with self._lock:
            if self._state is not SessionState.OPEN:
                raise SessionProtocolError("control session is not open")
            if request.protocol_version != PROTOCOL_VERSION:
                raise SessionProtocolError(
                    f"unsupported protocol version: {request.protocol_version}"
                )
            if request.request_id in self._handles:
                raise SessionProtocolError(
                    f"request ID already used: {request.request_id}"
                )
            handle = RequestHandle(request)
            self._handles[request.request_id] = handle
            return handle

    async def dispatch(self, handle: RequestHandle) -> bool:
        """Reserve dispatch capacity or commit a structured busy rejection."""

        async with self._lock:
            if self._handles.get(handle.request_id) is not handle:
                raise SessionProtocolError("request handle does not belong to session")
            if self._state is not SessionState.OPEN:
                await handle.interrupt("control session closed before dispatch")
                return False
            in_flight = sum(
                candidate.state is RequestState.DISPATCHED
                for candidate in self._handles.values()
            )
            if in_flight >= self.max_in_flight:
                await handle.reject(
                    ControlError(
                        code="gateway.busy",
                        message="session in-flight request limit reached",
                        origin=ControlErrorOrigin.GATEWAY,
                        retryable=True,
                    )
                )
                return False
            return await handle.mark_dispatched()

    async def interrupt(
        self, request_id: RequestId, reason: str = "request interrupted"
    ) -> bool:
        """Interrupt one admitted unreplied request in this session."""

        async with self._lock:
            handle = self._handles.get(request_id)
        return False if handle is None else await handle.interrupt(reason)

    async def close(self, reason: str = "control session closed") -> None:
        """Stop admission and interrupt every unreplied request exactly once."""

        async with self._lock:
            if self._state is SessionState.CLOSED:
                return
            self._state = SessionState.CLOSING
            handles = tuple(self._handles.values())
        await asyncio.gather(*(handle.interrupt(reason) for handle in handles))
        async with self._lock:
            self._state = SessionState.CLOSED
