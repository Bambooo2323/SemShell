"""Shared structured Action codec used by every operator Process."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from semshell.kernel import (
    Cancel,
    DiscoverImages,
    Exit,
    Send,
    Spawn,
    Wait,
    Yield,
)
from semshell.kernel.actions import ProcessAction
from semshell.security import Authority, Permission
from semshell.software.image import ProcessSpec


def action_from_data(value: Any) -> ProcessAction:
    """Decode one transport-neutral mapping into a Process Action."""

    if not isinstance(value, Mapping):
        raise TypeError("action must be a mapping")
    data = cast(Mapping[str, Any], value)
    action = data.get("action")
    if action == "yield":
        return Yield()
    if action == "discover_images":
        return DiscoverImages()
    if action == "exit":
        return Exit(data.get("result"))
    if action == "send":
        return Send(int(data["target_pid"]), data.get("payload"))
    if action == "cancel":
        return Cancel(
            int(data["target_pid"]),
            reason=str(data.get("reason", "cancelled")),
        )
    if action == "wait":
        return Wait(
            tuple(int(pid) for pid in data.get("child_pids", ())),
        )
    if action == "spawn":
        raw_specs = data.get("specs")
        if not isinstance(raw_specs, list) or not raw_specs:
            raise ValueError("spawn action requires a non-empty specs list")
        return Spawn(
            tuple(_spec_from_data(item) for item in raw_specs),
        )
    raise ValueError(f"unsupported action: {action!r}")


def _spec_from_data(value: Any) -> ProcessSpec:
    if not isinstance(value, Mapping):
        raise TypeError("process spec must be a mapping")
    data = cast(Mapping[str, Any], value)
    raw_permissions = data.get("requested_authority", ())
    if not isinstance(raw_permissions, (list, tuple)):
        raise TypeError("requested_authority must be a list")
    permissions = []
    for item in raw_permissions:
        if not isinstance(item, Mapping):
            raise TypeError("permission must be a mapping")
        permissions.append(
            Permission(str(item["capability"]), cast(str | None, item.get("scope")))
        )
    return ProcessSpec(
        image=cast(str | None, data.get("image")),
        capability=cast(str | None, data.get("capability")),
        provider=cast(str | None, data.get("provider")),
        input=data.get("input"),
        requested_authority=Authority.of(permissions),
    )
