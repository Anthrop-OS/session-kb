"""Load user-supplied extra patterns from a YAML file → ScrubProvider.

This is the ``--extra-patterns`` integration point. Pattern files are simple
YAML lists — no external tool required:

.. code-block:: yaml

    patterns:
      - id: my-internal-token
        regex: "myapp_tok_[A-Za-z0-9]{40}"
      - id: internal-api-key
        regex: "INTERNAL-[A-F0-9]{32}"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .interface import Finding

try:
    import yaml  # type: ignore[import-untyped]

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


@dataclass
class _PatternRule:
    id: str
    compiled: re.Pattern[str]


def _load_rules(path: Path) -> list[_PatternRule]:
    if not _YAML_AVAILABLE:
        raise ImportError(
            "PyYAML is required for --extra-patterns. Install: pip install pyyaml"
        )
    data: dict[str, Any] = yaml.safe_load(path.read_text())
    rules: list[_PatternRule] = []
    for entry in data.get("patterns", []):
        rules.append(_PatternRule(
            id=entry["id"],
            compiled=re.compile(entry["regex"]),
        ))
    return rules


class ExtraPatternsScrubProvider:
    """ScrubProvider from a user-supplied YAML pattern file."""

    def __init__(self, path: str | Path) -> None:
        self._rules = _load_rules(Path(path))

    def scan(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for rule in self._rules:
            for m in rule.compiled.finditer(text):
                findings.append(Finding(
                    start=m.start(),
                    end=m.end(),
                    type=f"extra:{rule.id}",
                    value=m.group(),
                ))
        return findings
