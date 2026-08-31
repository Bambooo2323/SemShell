"""Portable guest-path validation shared by demonstration bridges."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from semshell.resources.bridge import ResourceBridgeError
from semshell.resources.types import ResourceErrorCode

SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def read_text_path(
    value: Any, *, max_path_length: int, max_segments: int
) -> tuple[str, ...]:
    """Validate the exact portable read_text input and return path segments."""

    if not isinstance(value, Mapping) or set(value) != {"path"}:
        raise ResourceBridgeError(ResourceErrorCode.MALFORMED_INPUT)
    path = value["path"]
    if (
        not isinstance(path, str)
        or not path
        or len(path) > max_path_length
        or path.startswith("/")
        or "\\" in path
        or ":" in path
        or "\x00" in path
    ):
        raise ResourceBridgeError(ResourceErrorCode.MALFORMED_INPUT)
    segments = tuple(path.split("/"))
    if (
        len(segments) > max_segments
        or any(
            segment in {"", ".", ".."} or SEGMENT_PATTERN.fullmatch(segment) is None
            for segment in segments
        )
    ):
        raise ResourceBridgeError(ResourceErrorCode.MALFORMED_INPUT)
    return segments
