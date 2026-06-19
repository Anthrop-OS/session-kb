"""Batteries-included scrub provider — works out of the box with no external tools.

Covers: high-entropy strings, standard secret patterns (AWS, GitHub, generic
API keys, JWTs, PEM blocks). This is the baseline; external tools (gitleaks,
trufflehog) and user-supplied patterns extend it via --extra-patterns.
"""

from __future__ import annotations

import math
import re

from .interface import Finding, redact

# -- Standard secret patterns (public knowledge, from gitleaks/trufflehog OSS rules) --

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws-access-key", re.compile(r"(?<![A-Z0-9])(AKIA[0-9A-Z]{16})(?![A-Z0-9])")),
    ("github-pat-classic", re.compile(r"ghp_[A-Za-z0-9]{36,}")),
    ("github-pat-fine", re.compile(r"github_pat_[A-Za-z0-9_]{82,}")),
    ("github-oauth", re.compile(r"gho_[A-Za-z0-9]{36,}")),
    ("github-app-token", re.compile(r"(?:ghu|ghs)_[A-Za-z0-9]{36,}")),
    ("github-refresh-token", re.compile(r"ghr_[A-Za-z0-9]{36,}")),
    ("generic-api-key", re.compile(r"(?:sk|api|key|token|secret|password)[-_](?:[a-z]+[-_])*[A-Za-z0-9]{32,}")),
    ("slack-token", re.compile(r"xox[bpors]-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("pem-private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("1password-sa-token", re.compile(r"ops_[A-Za-z0-9_-]{50,}")),
    ("age-secret-key", re.compile(r"AGE-SECRET-KEY-[A-Z0-9]{59}")),
]

# -- Entropy detection for high-entropy strings not caught by patterns --

_ENTROPY_THRESHOLD = 4.5
_ENTROPY_MIN_LEN = 20
_HIGH_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/=_-]{20,}")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


class BuiltinScrubProvider:
    """Batteries-included provider: pattern matching + entropy detection."""

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        seen_spans: set[tuple[int, int]] = set()

        for rule_id, pattern in _PATTERNS:
            for m in pattern.finditer(text):
                span = (m.start(), m.end())
                if span not in seen_spans:
                    seen_spans.add(span)
                    findings.append(Finding(
                        start=m.start(), end=m.end(),
                        type=rule_id, value=m.group(),
                    ))

        for m in _HIGH_ENTROPY_RE.finditer(text):
            span = (m.start(), m.end())
            if span in seen_spans:
                continue
            candidate = m.group()
            if len(candidate) >= _ENTROPY_MIN_LEN and _shannon_entropy(candidate) >= _ENTROPY_THRESHOLD:
                seen_spans.add(span)
                findings.append(Finding(
                    start=m.start(), end=m.end(),
                    type="high-entropy", value=candidate,
                ))

        return findings

    def redact(self, text: str) -> str:
        return redact(text, self.scan(text))
