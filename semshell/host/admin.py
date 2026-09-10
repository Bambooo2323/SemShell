"""Small trusted Host administration facade for architecture demos."""

from __future__ import annotations

from semshell.kernel.kernel import ProcessKernel
from semshell.kernel.process import CancelMode, ProcessResult, ProcessSnapshot
from semshell.security import Authority, Principal
from semshell.software.image import ProcessSpec


class HostAdmin:
    """Expose lifecycle administration without impersonating a Process."""

    __slots__ = ("_kernel",)

    def __init__(self, kernel: ProcessKernel) -> None:
        self._kernel = kernel

    async def start(self) -> None:
        await self._kernel.start()

    async def spawn(
        self,
        spec: ProcessSpec,
        principal: Principal,
        authority_ceiling: Authority | None,
    ) -> int:
        return await self._kernel.spawn(
            spec,
            principal=principal,
            authority_ceiling=authority_ceiling,
        )

    def inspect(self, pid: int) -> ProcessSnapshot:
        return self._kernel.inspect(pid)

    def tree(self, pid: int) -> tuple[ProcessSnapshot, ...]:
        return self._kernel.tree(pid)

    async def wait(self, pid: int) -> ProcessResult:
        return await self._kernel.wait(pid)

    async def cancel(self, pid: int, reason: str) -> ProcessResult:
        return await self._kernel.cancel(pid, mode=CancelMode.TREE, reason=reason)

    async def stop(self) -> None:
        await self._kernel.stop()
