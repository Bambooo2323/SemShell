"""SemShell public API."""

from semshell.kernel.actions import (
    Cancel,
    Exit,
    Fail,
    Send,
    Spawn,
    Wait,
    Yield,
)
from semshell.kernel.kernel import ProcessKernel
from semshell.kernel.process import (
    ErrorOrigin,
    ProcessError,
    ProcessResult,
    ProcessState,
)
from semshell.software.image import (
    CapabilitySpec,
    ProcessImage,
    ProcessImageDescriptor,
    ProcessSpec,
)

__version__ = "0.1.0.dev0"

__all__ = [
    "Cancel",
    "CapabilitySpec",
    "ErrorOrigin",
    "Exit",
    "Fail",
    "ProcessError",
    "ProcessImage",
    "ProcessImageDescriptor",
    "ProcessKernel",
    "ProcessResult",
    "ProcessSpec",
    "ProcessState",
    "Send",
    "Spawn",
    "Wait",
    "Yield",
    "__version__",
]
