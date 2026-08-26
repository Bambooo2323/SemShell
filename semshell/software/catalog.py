"""Dynamic in-memory process-image catalog."""

from __future__ import annotations

from collections import defaultdict

from semshell.software.image import ProcessImage


class ProcessCatalog:
    """Store exact image versions and discover capability providers."""

    def __init__(self) -> None:
        self._images: dict[str, ProcessImage] = {}
        self._providers: dict[str, set[str]] = defaultdict(set)

    def register(self, image: ProcessImage) -> None:
        """Register an exact image version without replacing an existing one."""

        if image.reference in self._images:
            raise ValueError(f"duplicate process image: {image.reference}")
        self._images[image.reference] = image
        for capability in image.capabilities:
            self._providers[capability.name].add(image.reference)

    def unregister(self, reference: str) -> ProcessImage:
        """Remove and return one exact image version."""

        image = self._images.pop(reference, None)
        if image is None:
            raise LookupError(f"unknown process image: {reference}")
        for capability in image.capabilities:
            providers = self._providers[capability.name]
            providers.discard(reference)
            if not providers:
                del self._providers[capability.name]
        return image

    def get(self, reference: str) -> ProcessImage | None:
        """Return an exact image version, if registered."""

        return self._images.get(reference)

    def list_images(self) -> tuple[ProcessImage, ...]:
        """Return images in deterministic reference order."""

        return tuple(self._images[key] for key in sorted(self._images))

    def providers_for(self, capability: str) -> tuple[ProcessImage, ...]:
        """Return deterministic providers without resolving ambiguity."""

        references = sorted(self._providers.get(capability, ()))
        return tuple(self._images[reference] for reference in references)

    def resolve_image(self, reference: str) -> ProcessImage:
        """Resolve one exact image reference."""

        image = self.get(reference)
        if image is None:
            raise LookupError(f"unknown process image: {reference}")
        return image

    def resolve_capability(
        self, capability: str, *, provider: str | None = None
    ) -> ProcessImage:
        """Resolve uniquely or validate an exact caller-selected provider."""

        providers = self.providers_for(capability)
        if not providers:
            raise LookupError(f"unknown capability: {capability}")
        if provider is not None:
            selected = self.get(provider)
            if selected is None:
                raise LookupError(f"unknown process image: {provider}")
            if selected not in providers:
                raise LookupError(
                    f"image {provider!r} does not provide capability {capability!r}"
                )
            return selected
        if len(providers) > 1:
            references = ", ".join(image.reference for image in providers)
            raise LookupError(
                f"ambiguous capability {capability!r}; providers: {references}"
            )
        return providers[0]

    def resolve(
        self,
        *,
        image: str | None,
        capability: str | None,
        provider: str | None = None,
    ) -> ProcessImage:
        """Resolve the exclusive strategy carried by a ProcessSpec."""

        if image is not None:
            if provider is not None:
                raise ValueError("provider cannot be used with an exact image")
            return self.resolve_image(image)
        if capability is not None:
            return self.resolve_capability(capability, provider=provider)
        raise ValueError("an image reference or capability is required")
