"""Canonical record schema — the harness-agnostic connector output contract.

This is the single boundary between connectors and the rest of the pipeline.
A connector's only job is to map a native transcript onto these records; every
downstream stage (chunker / embed / index / search) reads ONLY this schema and
never branches on the source harness.

These are Pydantic v2 models so the contract is enforced (connectors validate at
the boundary) and exportable as language-neutral JSON Schema (``model_json_schema``
→ ``docs/schema/*.json``), so a non-Python connector can validate against the same
contract. ``model_config`` forbids extra keys: an unknown field is a connector bug,
not silently dropped data.

Layering note
-------------
Agnosticism applies at this (derived / L1) layer only. The raw L0 layer keeps
each harness's native format, full-fidelity and encrypted; ``raw_ptr`` resolves
back into it. So these records do not need to be lossless — they are the
searchable projection, not the system of record.

Record types
------------
One session manifest plus three content grains (each serialized to its own jsonl
so they stay independently git-diffable):

- ``SessionRecord``   — one per session. The manifest: the canonical ``host``
                        axis (analytics slice by host × workspace), workspace /
                        project context, and the L0 incremental ingest cursor.
                        Turns join back to it via ``session_id``; host/workspace
                        are NOT repeated on every turn.
- ``TurnRecord``      — one per message (user / agent / tool). Holds the scrubbed
                        verbatim text that FTS5 indexes.
- ``ChunkRecord``     — one per exchange (the embedding unit). Records what text
                        was embedded (verbatim vs an LLM summary, for over-cap
                        exchanges) so rebuilds need no inference.
- ``EmbeddingRecord`` — one per exchange. The vector only, keyed by exchange_id +
                        content_hash, kept apart so re-embedding never churns text.

Exchange boundary
-----------------
An *exchange* is the embedding/chunk unit: one user message and every agent / tool
message that follows it, up to (but excluding) the next user message. The
connector mints one ``exchange_id`` at each ``actor="user"`` boundary and stamps
it onto all turns of that exchange. Connector and chunker MUST agree on this rule;
it is the contract, not an implementation detail.

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

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"

Actor = Literal["user", "agent", "tool"]
EmbedSource = Literal["raw", "summary"]

#: content_hash convention: ``sha256:`` + lowercase hex digest. Encoded in the
#: JSON Schema (``pattern``) so a non-Python connector validates the same shape.
CONTENT_HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"


def _ensure_aware_iso8601(v: str) -> str:
    """Reject non-ISO-8601 or timezone-naive timestamps.

    Ordering keys off ``seq`` (not ``ts``), but DuckDB time-bucket analytics and
    the 6h incremental window depend on ``ts`` being a parseable, unambiguous
    instant — so format drift across connectors is a contract violation, caught
    here rather than at query time.
    """
    try:
        parsed = datetime.fromisoformat(v)
    except ValueError as exc:  # not ISO-8601 at all
        raise ValueError(f"timestamp is not ISO-8601: {v!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware (got naive): {v!r}")
    return v


#: ISO-8601, timezone-aware. Carried as a string (the canonical wire form) with a
#: parse+tz check; ``format: date-time`` is advertised in the exported JSON Schema.
TimestampStr = Annotated[str, AfterValidator(_ensure_aware_iso8601)]

_TS_SCHEMA = {"format": "date-time"}


class _Record(BaseModel):
    """Base for all canonical records: extra keys are a contract violation."""

    model_config = ConfigDict(extra="forbid")


class Source(_Record):
    harness: str = Field(
        description="the tool/app, e.g. 'claude-code' (our axis; no OTel equivalent)"
    )
    connector_version: str
    provider: str | None = Field(
        default=None, description="model vendor, e.g. 'anthropic' ~ gen_ai.provider.name"
    )
    model: str | None = Field(default=None, description="the LLM, ~ gen_ai.request.model")


class RawPtr(_Record):
    """Pointer into the encrypted L0 raw layer for full-fidelity recovery.

    ``uuids`` is the primary anchor: native message ids survive file rewrites,
    line numbers do not. ``span`` is a best-effort line range for convenience.
    """

    uuids: list[str] = Field(
        default_factory=list, description="primary L0 anchor; native message ids"
    )
    span: tuple[int, int] | None = Field(default=None, description="best-effort line range")


class ToolCall(_Record):
    """One tool invocation carried on an ``actor="agent"`` turn.

    Paired to the answering ``actor="tool"`` turn via ``id`` ↔ ``tool_call_id``.
    ``arguments`` stays open (tool-defined), but the envelope is typed so the
    correlation keys cannot silently drift.
    """

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict, description="tool-defined payload")


class SessionRecord(_Record):
    """Session-level manifest — the system of record for session metadata.

    One per session. The canonical ``host`` axis and workspace context live here
    (not repeated on every turn); ``TurnRecord``s join back via ``session_id``.
    Also the home of the incremental ingest cursor, so per-host scheduling resumes
    from where it stopped without a separate state DB.
    """

    session_id: str
    host: str = Field(
        description="canonical host the session ran on (e.g. 'tp-server'); the analytics host axis"
    )
    source: Source
    workspace: str | None = Field(
        default=None, description="workspace root slug (host-relative), scrubbed of any home prefix"
    )
    cwd: str | None = Field(default=None, description="scrubbed of any home prefix")
    project: str | None = Field(default=None, description="repo / project slug")
    git_branch: str | None = None
    started_at: TimestampStr = Field(
        description="ISO-8601, timezone-aware; first turn's ts", json_schema_extra=_TS_SCHEMA
    )
    ended_at: TimestampStr | None = Field(
        default=None,
        description="ISO-8601, timezone-aware; None while the session is open",
        json_schema_extra=_TS_SCHEMA,
    )
    turn_count: int | None = Field(default=None, description="turns ingested so far")
    raw_ptr: RawPtr = Field(description="anchor to the L0 session file")
    cursor: str | None = Field(
        default=None, description="L0 incremental anchor: last ingested native id"
    )
    record_type: Literal["session"] = "session"
    schema_version: str = SCHEMA_VERSION


class TurnRecord(_Record):
    """One message. ``message`` is scrubbed verbatim and is the FTS5 source."""

    session_id: str
    seq: int = Field(description="monotonic per session; the stable record-ordering key")
    exchange_id: str = Field(description="groups messages into one embedding unit (the chunk key)")
    actor: Actor
    message: str = Field(description="scrubbed verbatim text")
    content_hash: str = Field(
        pattern=CONTENT_HASH_PATTERN,
        description="sha256 of the scrubbed message; turn-level re-derive / idempotency anchor",
    )
    source: Source
    raw_ptr: RawPtr
    ts: TimestampStr = Field(description="ISO-8601, timezone-aware", json_schema_extra=_TS_SCHEMA)

    # threading / context (common-ish; nullable, populated when the harness has it)
    parent_id: str | None = Field(default=None, description="normalized threading pointer (DAG)")
    cwd: str | None = Field(default=None, description="scrubbed of any home prefix")
    project: str | None = Field(default=None, description="repo / project slug")
    git_branch: str | None = None
    lang: str | None = None

    # usage (~ gen_ai.usage.*)
    input_tokens: int | None = None
    output_tokens: int | None = None

    # tool correlation: agent records carry the calls; a tool record names the
    # call it answers via ``tool_call_id`` (paired by id, per the converging shape)
    tool_calls: list[ToolCall] = Field(
        default_factory=list, description="{id, name, arguments} per call (agent turns)"
    )
    tool_call_id: str | None = Field(
        default=None, description="set on actor=tool; names the call answered"
    )

    files_touched: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list, description="enrichment; empty in MVP")
    topics: list[str] = Field(default_factory=list, description="enrichment; empty in MVP")

    redacted: bool = False
    scrub_rules_version: str | None = None

    # harness-specific fidelity, keyed by harness kind. Downstream MUST NOT read.
    ext: dict[str, Any] = Field(
        default_factory=dict, description="harness-keyed native fidelity; downstream MUST NOT read"
    )

    record_type: Literal["turn"] = "turn"
    schema_version: str = SCHEMA_VERSION


class ChunkRecord(_Record):
    """One exchange = the embedding unit. Records what text was embedded.

    For exchanges within the token cap, ``embed_source="raw"`` and the embedded
    text is the concatenated verbatim turns (``summary`` is None). For larger
    exchanges, ``embed_source="summary"`` and ``summary`` holds the persisted
    LLM summary that was embedded — persisted so rebuilds never re-run inference.
    """

    exchange_id: str
    session_id: str
    embed_source: EmbedSource
    content_hash: str = Field(
        pattern=CONTENT_HASH_PATTERN,
        description="sha256 of the exact embedded text; ties to EmbeddingRecord",
    )
    summary: str | None = Field(default=None, description="set iff embed_source == 'summary'")
    record_type: Literal["chunk"] = "chunk"
    schema_version: str = SCHEMA_VERSION


class EmbeddingRecord(_Record):
    """One vector per exchange. Kept separate so re-embedding never churns text."""

    exchange_id: str
    model: str = Field(description="the embedding model (distinct from Source.model, the LLM)")
    dim: int
    embedding: list[float]
    content_hash: str = Field(
        pattern=CONTENT_HASH_PATTERN,
        description="must match the ChunkRecord; rebuild-verification anchor",
    )
    record_type: Literal["embedding"] = "embedding"
    schema_version: str = SCHEMA_VERSION


class ClaudeCodeExt(_Record):
    """Documents the ``ext["claude_code"]`` payload (native fidelity).

    Carried for re-derivation / debugging only — never on the retrieval hot path.
    Stored as a plain dict under ``TurnRecord.ext["claude_code"]``; this model
    exists to document and (optionally) validate that payload.
    """

    parent_uuid: str | None = None
    is_sidechain: bool | None = None
    is_meta: bool | None = None
    request_id: str | None = None
    version: str | None = None
    tool_use_result: Any | None = None


#: The record models whose JSON Schema is exported as the language-neutral contract.
EXPORTED_MODELS: dict[str, type[_Record]] = {
    "session": SessionRecord,
    "turn": TurnRecord,
    "chunk": ChunkRecord,
    "embedding": EmbeddingRecord,
    "claude_code_ext": ClaudeCodeExt,
}


def json_schemas() -> dict[str, dict[str, Any]]:
    """Return the JSON Schema for every exported record model, keyed by name."""
    return {name: model.model_json_schema() for name, model in EXPORTED_MODELS.items()}
