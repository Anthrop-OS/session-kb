# Canonical turn record

The harness-agnostic contract every connector emits. Field names align with
OpenTelemetry GenAI semantic conventions where they overlap; the record is
**not** an OTel span — alignment is naming-only.

```jsonc
{
  "schema_version": "1",
  "session_id": "...",
  "turn": 10,
  "chunk_id": "<session>:t10",
  "actor": "user|agent|tool",
  "message_type": "raw|summary",
  "message": "...",
  "source": { "harness": "claude-code", "model": "...", "connector_version": "0.1.0" },
  "raw_ptr": { "span": [10, 10], "uuids": ["..."] },
  "ts": "2026-06-18T20:55:10Z",
  "lang": "en",
  "orig_tokens": 4200,
  "tool_calls": [],
  "files_touched": [],
  "decisions": [],
  "topics": [],
  "redacted": true,
  "scrub_rules_version": "1"
}
```

Embeddings are a **separate** record type so turn records stay readable and
git-diffable:

```jsonc
{ "type": "embedding", "chunk_id": "<session>:t10", "model": "minilm-v2", "dim": 384, "vec": [/* … */] }
```

## Notes

- `actor=tool` isolates tool output (where secrets and noise concentrate) so it
  can be scrubbed differently from human/agent prose.
- `raw_ptr` resolves into the encrypted L0 layer for full-fidelity recovery; the
  derived layers never need to hold the original bytes.
- `message_type` is set by the chunker: `raw` (embedded verbatim) for exchanges
  within the token cap, `summary` for larger ones.
- `redacted` + `scrub_rules_version` make the scrub auditable and re-runnable; a
  scrub-logic change means re-deriving from L0, never rewriting in place.
