"""Composite provider — unions findings from multiple ScrubProviders."""

from __future__ import annotations

from .interface import Finding, ScrubProvider, redact


class CompositeScrubProvider:
    """Run multiple providers and union their findings (deduped by span)."""

    def __init__(self, providers: list[ScrubProvider]) -> None:
        self._providers = providers

    def scan(self, text: str) -> list[Finding]:
        seen: set[tuple[int, int]] = set()
        merged: list[Finding] = []
        for provider in self._providers:
            for f in provider.scan(text):
                span = (f.start, f.end)
                if span not in seen:
                    seen.add(span)
                    merged.append(f)
        return merged

    def redact(self, text: str) -> str:
        return redact(text, self.scan(text))
