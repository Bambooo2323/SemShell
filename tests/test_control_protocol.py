"""Conformance tests for transport-neutral request and session state."""

from __future__ import annotations

import asyncio

import pytest

from semshell.control import (
    ControlError,
    ControlErrorOrigin,
    ControlRequest,
    ControlSession,
    ReplyStatus,
    RequestId,
    RequestState,
    SessionProtocolError,
)
from semshell.kernel import Send
from semshell.kernel.operations import ListImages
from semshell.security import Authority, Principal


def request(value: str) -> ControlRequest:
    return ControlRequest(RequestId(value), ListImages())


def session(*, max_in_flight: int = 2) -> ControlSession:
    return ControlSession(
        principal=Principal.parse("human:alice"),
        authority=Authority.empty(),
        max_in_flight=max_in_flight,
    )


@pytest.mark.asyncio
async def test_request_id_is_reserved_for_session_lifetime() -> None:
    control_session = session()
    first = await control_session.admit(request("one"))
    await first.succeed(())

    with pytest.raises(SessionProtocolError, match="already used"):
        await control_session.admit(request("one"))


@pytest.mark.asyncio
async def test_unsupported_version_is_rejected_before_admission() -> None:
    control_session = session()
    unsupported = ControlRequest(RequestId("one"), ListImages(), protocol_version="9.9")

    with pytest.raises(SessionProtocolError, match="unsupported protocol"):
        await control_session.admit(unsupported)

    admitted = await control_session.admit(request("one"))
    assert admitted.state is RequestState.ADMITTED


def test_external_session_cannot_originate_process_ipc() -> None:
    with pytest.raises(TypeError, match="not available"):
        ControlRequest(RequestId("one"), Send(target_pid=1, payload="forged"))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_reply_gate_commits_exactly_one_terminal_reply() -> None:
    handle = await session().admit(request("one"))
    error = ControlError(
        code="kernel.rejected",
        message="rejected",
        origin=ControlErrorOrigin.KERNEL,
    )

    succeeded, rejected, interrupted = await asyncio.gather(
        handle.succeed(("image@1",)),
        handle.reject(error),
        handle.interrupt(),
    )
    reply = await handle.wait_reply()

    assert sum((succeeded, rejected, interrupted)) == 1
    assert handle.state is RequestState.REPLIED
    assert reply.status in {
        ReplyStatus.SUCCEEDED,
        ReplyStatus.REJECTED,
        ReplyStatus.INTERRUPTED,
    }


@pytest.mark.asyncio
async def test_interrupt_before_dispatch_is_not_lost() -> None:
    handle = await session().admit(request("one"))

    assert await handle.interrupt()
    assert not await handle.mark_dispatched()
    assert (await handle.wait_reply()).status is ReplyStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_capacity_rejection_does_not_consume_dispatch_slot() -> None:
    control_session = session(max_in_flight=1)
    first = await control_session.admit(request("one"))
    second = await control_session.admit(request("two"))

    assert await control_session.dispatch(first)
    assert not await control_session.dispatch(second)
    second_reply = await second.wait_reply()
    assert second_reply.status is ReplyStatus.REJECTED
    assert second_reply.error is not None
    assert second_reply.error.code == "gateway.busy"

    await first.succeed(())
    third = await control_session.admit(request("three"))
    assert await control_session.dispatch(third)


@pytest.mark.asyncio
async def test_session_close_interrupts_unreplied_requests_only() -> None:
    control_session = session()
    complete = await control_session.admit(request("complete"))
    pending = await control_session.admit(request("pending"))
    await complete.succeed(())

    await control_session.close()

    assert (await complete.wait_reply()).status is ReplyStatus.SUCCEEDED
    assert (await pending.wait_reply()).status is ReplyStatus.INTERRUPTED
    assert not await control_session.interrupt(RequestId("missing"))
    with pytest.raises(SessionProtocolError, match="not open"):
        await control_session.admit(request("late"))
