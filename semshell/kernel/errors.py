"""Exceptions raised by the SemShell kernel API."""


class KernelError(RuntimeError):
    """Base class for deterministic kernel API failures."""


class KernelNotRunning(KernelError):
    """Raised when an operation requires a running kernel."""


class InvalidKernelState(KernelError):
    """Raised when a lifecycle operation is invalid in the current state."""


class InvalidAction(KernelError):
    """Raised for malformed or unsupported process actions."""


class ProcessNotFound(KernelError):
    """Raised when a PID is unknown to the live kernel."""


class OperationDenied(KernelError):
    """Raised at an external API boundary when policy rejects an operation."""
