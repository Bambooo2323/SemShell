"""Trusted Host adapters around the SemShell semantic VM."""

from semshell.host.admin import HostAdmin
from semshell.host.console import ConsoleBridge

__all__ = ["ConsoleBridge", "HostAdmin"]
