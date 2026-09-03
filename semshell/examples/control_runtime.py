"""Deterministic Host assembly for the version 0.3 local Control proof."""

from __future__ import annotations

from dataclasses import dataclass

from semshell.control import ControlGateway, ControlSession
from semshell.examples.architecture_demo import build_demo_catalog
from semshell.kernel import ProcessKernel
from semshell.security import Authority, Principal


@dataclass(frozen=True, slots=True)
class ControlRuntime:
    """Trusted Host objects owned by one local CLI lifetime."""

    kernel: ProcessKernel
    gateway: ControlGateway
    session: ControlSession


async def build_control_runtime() -> ControlRuntime:
    """Start the deterministic demo runtime and its local administration session."""

    kernel = ProcessKernel(build_demo_catalog("human"))
    await kernel.start()
    gateway = ControlGateway(kernel)
    session = gateway.open_session(
        principal=Principal.parse("human:local-control"),
        authority=Authority.empty(),
    )
    return ControlRuntime(kernel, gateway, session)
