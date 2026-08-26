"""Structured permissions carried by process executions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class Permission:
    """One capability permission with an exact optional scope."""

    capability: str
    scope: str | None = None

    def __post_init__(self) -> None:
        if not self.capability:
            raise ValueError("permission capability must not be empty")


@dataclass(frozen=True, slots=True)
class Authority:
    """Immutable set of structured permissions."""

    permissions: frozenset[Permission] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "permissions", frozenset(self.permissions))

    @classmethod
    def empty(cls) -> Authority:
        """Return an authority containing no permissions."""

        return cls()

    @classmethod
    def of(cls, permissions: Iterable[Permission]) -> Authority:
        """Build authority from an iterable of permissions."""

        return cls(frozenset(permissions))

    def is_subset_of(self, other: Authority) -> bool:
        """Return whether every exact permission is present in ``other``."""

        return self.permissions <= other.permissions

    def intersection(self, *others: Authority) -> Authority:
        """Return the exact permission intersection with other authorities."""

        result = self.permissions
        for other in others:
            result = result & other.permissions
        return Authority(result)

    def union(self, *others: Authority) -> Authority:
        """Return the exact permission union with other authorities."""

        result = self.permissions
        for other in others:
            result = result | other.permissions
        return Authority(result)

    def difference(self, other: Authority) -> Authority:
        """Return permissions present here but absent from ``other``."""

        return Authority(self.permissions - other.permissions)

    def reduced_to(self, requested: Authority) -> Authority:
        """Reduce this authority to the requested exact permission subset."""

        return self.intersection(requested)
