"""Canonical record schema — the harness-agnostic connector output contract.

This is the single boundary between connectors and the rest of the pipeline.
A connector's only job is to map a native transcript onto these records; every
downstream stage (chunker / embed / index / search) reads ONLY this schema and
never branches on the source harness.

Layering note
-------------
Agnosticism applies at this (derived / L1) layer only. The raw L0 layer keeps
each harness's native format, full-fidelity and encrypted; ``raw_ptr`` resolves
back into it. So these records do not need to be lossless — they are the
searchable projection, not the system of record.

Three record types, three grains (each serialized to its own jsonl so they stay
independently git-diffable):

- ``TurnRecord``      — one per message (user / agent / tool). Holds the scrubbed
                        verbatim text that FTS5 indexes.
- ``ChunkRecord``     — one per exchange (the embedding unit). Records what text
                        was embedded (verbatim vs an LLM summary, for over-cap
                        exchanges) so rebuilds need no inference.
- ``EmbeddingRecord`` — one per exchange. The vector only, keyed by exchange_id +
                        content_hash, kept apart so re-embedding never churns text.

Field-name alignment
--------------------
Scalar metadata names follow OpenTelemetry GenAI semantic conventions where they
overlap (``source.provider`` ↔ ``gen_ai.provider.name``, ``input_tokens`` ↔
``gen_ai.usage.input_tokens``). This is naming guidance only: OTel GenAI is still
Development-stability and expects renames, and these records are NOT OTel spans.
The message body follows the converging cross-vendor shape (role + typed parts);
here it is flattened to scrubbed text for the derived layer.

Harness-specific extension
--------------------------
Native fidelity that is not yet universal across harnesses (e.g. Claude Code's
``parentUuid`` / ``isSidechain``) lives in ``TurnRecord.ext``, a single
namespace keyed by harness kind (mirrors ADR-0010 D7). Downstream stages MUST
NOT read ``ext``; if a stage needs a field, promote it to the core (nullable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = "1"

Actor = Literal["user", "agent", "tool"]
EmbedSource = Literal["raw", "summary"]


@dataclass
class Source:
    harness: str  # the tool/app, e.g. "claude-code" (our axis; no OTel equivalent)
    connector_version: str
    provider: str | None = None  # model vendor, e.g. "anthropic" ~ gen_ai.provider.name
    model: str | None = None  # ~ gen_ai.request.model


@dataclass
class RawPtr:
    """Pointer into the encrypted L0 raw layer for full-fidelity recovery.

    ``uuids`` is the primary anchor: native message ids survive file rewrites,
    line numbers do not. ``span`` is a best-effort line range for convenience.
    """

    uuids: list[str] = field(default_factory=list)
    span: tuple[int, int] | None = None


@dataclass
class TurnRecord:
    """One message. ``message`` is scrubbed verbatim and is the FTS5 source."""

    session_id: str
    seq: int  # monotonic per session; the stable record-ordering key
    exchange_id: str  # groups messages into one embedding unit (the chunk key)
    actor: Actor
    message: str  # scrubbed verbatim text
    source: Source
    raw_ptr: RawPtr
    ts: str  # ISO-8601

    # threading / context (common-ish; nullable, populated when the harness has it)
    parent_id: str | None = None  # normalized threading pointer (DAG)
    cwd: str | None = None  # scrubbed of any home prefix
    project: str | None = None  # repo / project slug
    git_branch: str | None = None
    lang: str | None = None

    # usage (~ gen_ai.usage.*)
    input_tokens: int | None = None
    output_tokens: int | None = None

    # tool correlation: agent records carry the calls; a tool record names the
    # call it answers via ``tool_call_id`` (paired by id, per the converging shape)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)  # {id, name, arguments}
    tool_call_id: str | None = None

    files_touched: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)  # enrichment; empty in MVP
    topics: list[str] = field(default_factory=list)  # enrichment; empty in MVP

    redacted: bool = False
    scrub_rules_version: str | None = None

    # harness-specific fidelity, keyed by harness kind. Downstream MUST NOT read.
    ext: dict[str, Any] = field(default_factory=dict)

    record_type: Literal["turn"] = "turn"
    schema_version: str = SCHEMA_VERSION


@dataclass
class ChunkRecord:
    """One exchange = the embedding unit. Records what text was embedded.

    For exchanges within the token cap, ``embed_source="raw"`` and the embedded
    text is the concatenated verbatim turns (``summary`` is None). For larger
    exchanges, ``embed_source="summary"`` and ``summary`` holds the persisted
    LLM summary that was embedded — persisted so rebuilds never re-run inference.
    """

    exchange_id: str
    session_id: str
    embed_source: EmbedSource
    content_hash: str  # sha256 of the exact embedded text; ties to EmbeddingRecord
    summary: str | None = None  # set iff embed_source == "summary"
    record_type: Literal["chunk"] = "chunk"
    schema_version: str = SCHEMA_VERSION


@dataclass
class EmbeddingRecord:
    """One vector per exchange. Kept separate so re-embedding never churns text."""

    exchange_id: str
    model: str
    dim: int
    embedding: list[float]
    content_hash: str  # must match the ChunkRecord; rebuild-verification anchor
    record_type: Literal["embedding"] = "embedding"
    schema_version: str = SCHEMA_VERSION


@dataclass
class ClaudeCodeExt:
    """Documentation of the ``ext["claude_code"]`` payload (native fidelity).

    Carried for re-derivation / debugging only — never on the retrieval hot path.
    Stored as a plain dict under ``TurnRecord.ext["claude_code"]``.
    """

    parent_uuid: str | None = None
    is_sidechain: bool | None = None
    is_meta: bool | None = None
    request_id: str | None = None
    version: str | None = None
    tool_use_result: Any | None = None
