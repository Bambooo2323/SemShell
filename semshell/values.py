"""Immutable structured values shared across public SemShell boundaries."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any


def freeze_public_value(value: Any, _active: set[int] | None = None) -> Any:
    """Copy a JSON-like public value into recursively immutable containers."""

    if value is None or isinstance(value, (bool, int, str, datetime, Enum)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("public value numbers must be finite")
        return value
    if not isinstance(value, (list, tuple, set, frozenset, Mapping)):
        raise TypeError("public values must contain only structured data")

    active = set() if _active is None else _active
    identity = id(value)
    if identity in active:
        raise ValueError("public values must not contain cycles")
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            if any(not isinstance(key, str) for key in value):
                raise TypeError("public value mapping keys must be strings")
            return MappingProxyType(
                {key: freeze_public_value(item, active) for key, item in value.items()}
            )
        frozen = (freeze_public_value(item, active) for item in value)
        return frozenset(frozen) if isinstance(value, (set, frozenset)) else tuple(frozen)
    finally:
        active.remove(identity)
