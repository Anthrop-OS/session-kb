"""Claude Code connector: native session jsonl → canonical full-turn records.

Unlike a prompt-only analytics extractor (which keeps user messages only), the
KB connector emits the full turn stream: user + agent + tool. Edge cases to
handle at implementation time: sidechain entries and tool-result pairing.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ..schema import TurnRecord


def iter_turns(path: Path) -> Iterator[TurnRecord]:
    raise NotImplementedError("milestone: canonical schema + Claude Code connector")
