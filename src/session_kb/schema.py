"""Canonical turn record — the harness-agnostic connector output contract.

Field names align with OpenTelemetry GenAI semantic conventions where they
overlap (e.g. ``source.model`` ↔ ``gen_ai.request.model``). This is naming
alignment only; the record is NOT an OTel span.

The schema is the shared boundary between connectors and the rest of the
pipeline: a connector's sole job is to map a native transcript onto it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "1"

Actor = Literal["user", "agent", "tool"]
MessageType = Literal["raw", "summary"]


@dataclass
class Source:
    harness: str
    model: str | None
    connector_version: str


@dataclass
class RawPtr:
    """Pointer into the encrypted L0 raw layer for full-fidelity recovery."""

    span: tuple[int, int]
    uuids: list[str] = field(default_factory=list)


@dataclass
class TurnRecord:
    session_id: str
    turn: int
    chunk_id: str
    actor: Actor
    message_type: MessageType
    message: str
    source: Source
    raw_ptr: RawPtr
    ts: str
    lang: str | None = None
    orig_tokens: int | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    redacted: bool = False
    scrub_rules_version: str | None = None
    schema_version: str = SCHEMA_VERSION


@dataclass
class EmbeddingRecord:
    """Separate record type — keeps turn records readable / git-diffable."""

    chunk_id: str
    model: str
    dim: int
    vec: list[float]
    type: str = "embedding"
