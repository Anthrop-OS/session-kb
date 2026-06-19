"""ScrubProvider protocol — the contract for all secret scrub implementations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Finding:
    """A detected secret candidate."""

    start: int
    end: int
    type: str
    value: str


@runtime_checkable
class ScrubProvider(Protocol):
    """Interface that all scrub providers implement."""

    def scan(self, text: str) -> list[Finding]:
        """Return all secret candidates found in *text*."""
        ...


def tokenize(finding: Finding) -> str:
    """Deterministic, irreversible replacement token for a finding.

    Format: ``<CRED:type:sha256-prefix-12>``
    Same value always produces the same token (preserves cross-session correlation).
    """
    h = hashlib.sha256(finding.value.encode()).hexdigest()[:12]
    return f"<CRED:{finding.type}:{h}>"


def redact(text: str, findings: list[Finding]) -> str:
    """Replace all findings in *text* with deterministic tokens.

    Findings are applied right-to-left so indices stay valid.
    """
    result = text
    for f in sorted(findings, key=lambda f: f.start, reverse=True):
        result = result[: f.start] + tokenize(f) + result[f.end :]
    return result
