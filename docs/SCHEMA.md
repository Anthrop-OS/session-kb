# Canonical record schema

The harness-agnostic contract every connector emits. It is the **only** boundary
between connectors and the rest of the pipeline: a connector maps a native
transcript onto these records, and every downstream stage (chunker / embed /
index / search) reads only this schema — never the source harness.

## Source of truth

The contract is defined as Pydantic v2 models in
[`src/session_kb/schema.py`](../src/session_kb/schema.py) and exported to
language-neutral **JSON Schema** under [`docs/schema/`](schema/) — so a non-Python
connector validates against the same contract. The models reject unknown keys
(`extra="forbid"`): an unrecognized field is a connector bug, not silently dropped
data. Regenerate the JSON Schema after any model change with
`python scripts/gen_schema.py`; a CI drift-guard test fails if the committed files
fall out of sync. The JSONC blocks below are illustrative — the models and the
generated JSON Schema are authoritative.

## Where "agnostic" applies

| Layer | Agnostic? | Form |
|---|---|---|
| **L0 raw** | no — per-harness native | each harness's own format, full-fidelity, encrypted. `raw_ptr` resolves here. |
| **connector** | no — harness-specific *code* | one implementation per harness (`claude_code.py`, …), maps native → canonical |
| **L1 derived (this schema)** | **yes — one common schema** | downstream reads only this |

The derived layer does **not** need to be lossless: L0 is the system of record,
and `raw_ptr` recovers the structured original. These records are the searchable
*projection*.

## Three record types (three grains)

Each is serialized to its own jsonl file so they stay independently git-diffable.

### `TurnRecord` — one per message

Holds the scrubbed verbatim text that FTS5 indexes. `message` is **always**
verbatim (never a summary) so full-text recall never degrades on long exchanges.

```jsonc
{
  "record_type": "turn",
  "schema_version": "1",
  "session_id": "synthetic-session",
  "seq": 42,                       // monotonic per session; stable ordering key
  "exchange_id": "synthetic-session:x7",  // groups messages into one embed unit
  "actor": "user|agent|tool",
  "message": "...scrubbed verbatim...",
  "source": { "harness": "claude-code", "provider": "anthropic",
              "model": "...", "connector_version": "0.1.0" },
  "raw_ptr": { "uuids": ["..."], "span": [120, 124] },
  "ts": "2026-06-18T20:55:10Z",
  "parent_id": "...",              // normalized threading pointer (DAG)
  "cwd": "<repo>/sub/dir",         // scrubbed of any home prefix
  "project": "homelab-ops",
  "git_branch": "main",
  "lang": "en",
  "input_tokens": 4200,
  "output_tokens": 110,
  "tool_calls": [{ "id": "tc_1", "name": "Read", "arguments": {} }],
  "tool_call_id": null,            // set on actor=tool, names the call answered
  "files_touched": [],
  "decisions": [],                 // enrichment; empty in MVP
  "topics": [],                    // enrichment; empty in MVP
  "redacted": true,
  "scrub_rules_version": "1",
  "ext": { "claude_code": { "parent_uuid": "...", "is_sidechain": false } }
}
```

### `ChunkRecord` — one per exchange (the embedding unit)

Records *what text was embedded*. Persists the summary for over-cap exchanges so
rebuilds never re-run inference.

```jsonc
{
  "record_type": "chunk",
  "schema_version": "1",
  "exchange_id": "synthetic-session:x7",
  "session_id": "synthetic-session",
  "embed_source": "raw|summary",
  "content_hash": "sha256:...",    // of the exact embedded text
  "summary": null                  // set iff embed_source == "summary"
}
```

### `EmbeddingRecord` — one vector per exchange

Kept apart from text so re-embedding (model swap) never churns the text records.

```jsonc
{
  "record_type": "embedding",
  "schema_version": "1",
  "exchange_id": "synthetic-session:x7",
  "model": "minilm-v2",
  "dim": 384,
  "embedding": [/* … */],
  "content_hash": "sha256:..."     // must match the ChunkRecord
}
```

## Identity & threading

- `seq` — our own monotonic per-session ordinal (record grain). No standard
  provides a stable per-message id, so we mint one.
- `exchange_id` — the embedding/chunk key; all messages of one exchange (a user
  turn plus the agent/tool turns until the next user turn) share it.
- `raw_ptr.uuids` — the **primary** L0 anchor: native message ids survive file
  rewrites; line numbers (`span`) do not. (Claude Code note: a `messageId` on
  `file-history-snapshot` lines can collide with message `uuid` — key on
  `(type, uuid)` or filter snapshot lines when extracting.)
- `parent_id` — normalized threading pointer; the native value (e.g. Claude
  Code's `parentUuid`) is also preserved verbatim under `ext`.

## Harness-specific extension (`ext`)

A single namespace keyed by harness kind, mirroring ADR-0010 D7's per-agent
block. It carries native fidelity not yet common across harnesses (Claude Code:
`parent_uuid`, `is_sidechain`, `is_meta`, `request_id`, `version`,
`tool_use_result`). Two rules keep the core honest:

1. **Downstream MUST NOT read `ext`.** Chunker / embed / index / search touch
   only core fields.
2. **Promotion, not branching.** If a stage needs an `ext` field, promote it to a
   nullable core field. The acceptance test for the agnostic design is that
   adding a second harness adds a connector + a new `ext` key and changes **no**
   core field.

## Notes

- `actor=tool` isolates tool output (where secrets and noise concentrate) so it
  can be scrubbed differently — agnostically, without harness branching.
- `message_type` of old (`raw|summary`) moved off the per-message record onto the
  per-exchange `ChunkRecord.embed_source`, since the raw-vs-summary decision is a
  property of the exchange (the embedding unit), not of any single message.
- `redacted` + `scrub_rules_version` make the scrub auditable and re-runnable: a
  scrub-logic change means re-deriving from L0, never rewriting L1 in place.
- **Schema evolution**: because `L1 = f(L0)`, a version bump is handled by
  re-deriving from L0, not by migrating records in place.
- Field names track OpenTelemetry GenAI semantic conventions where they overlap
  (`source.provider`, `input_tokens`/`output_tokens`) but only as guidance — that
  spec is Development-stability and these records are not OTel spans.
