"""Identity value objects used as authority sources."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class Principal:
    """A stable namespace-qualified identity such as ``human:alice``."""

    namespace: str
    subject: str

    def __post_init__(self) -> None:
        if not self.namespace or ":" in self.namespace:
            raise ValueError(
                "principal namespace must be non-empty and contain no colon"
            )
        if not self.subject:
            raise ValueError("principal subject must not be empty")

    @classmethod
    def parse(cls, value: str) -> "Principal":
        """Parse a namespace-qualified principal ID."""

        namespace, separator, subject = value.partition(":")
        if not separator:
            raise ValueError("principal ID must use the form namespace:subject")
        return cls(namespace=namespace, subject=subject)

    def __str__(self) -> str:
        return f"{self.namespace}:{self.subject}"
