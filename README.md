# session-kb

Harness-agnostic archival & semantic retrieval for finished AI coding sessions.

> **Status: scaffold (pre-implementation).** The architecture is settled; the
> pipeline is not built yet. Modules raise `NotImplementedError` until the
> corresponding milestone lands. See [Status](#status).

## What it does

AI coding sessions (Claude Code today; other agents/harnesses via pluggable
connectors) produce rich context — decisions, debugging chains, file edits —
that is lost when a session ends. `session-kb` turns finished transcripts into
a searchable knowledge base so future sessions and humans can recover context.

```
finished session  →  connector  →  canonical turn records  →  chunk + embed
                                                                   ↓
   session-search "why did we pick restic over borg?"  ←  sqlite (FTS5 + vec)
```

## Design

### Three storage layers

| Layer | Contents | Home | In VCS? |
|---|---|---|---|
| **L0 raw** | full-fidelity transcript, secret-tokenized, encrypted, append-only | data plane (out of band) | no |
| **L1 derived** | scrubbed per-message records + summaries + embeddings (jsonl) | private data repo | yes |
| **L2 index** | sqlite FTS5 + sqlite-vec | local | no (gitignored) |

Invariants: `L2 = f(L1)`, `L1 = f(L0)`. Deleting L2 loses nothing; L1 is
re-derivable from L0. Embeddings are committed to L1 as jsonl records, so an
index rebuild needs **zero inference** — the model runs only at ingest (one
node) and at query time (to embed the query string).

**This repository holds tool code only — never session content.** Raw
transcripts are full-fidelity and stay encrypted out of band; scrubbing reduces
magnitude but is not the security boundary, encryption is. Data isolation is a
hard boundary: no session data lands here by construction.

### Canonical turn record

One harness-agnostic per-turn schema (field names aligned to OpenTelemetry
GenAI semantic conventions where they overlap; not the OTel span format).
A connector's only job is to map a native transcript format onto this schema.
See [`docs/SCHEMA.md`](docs/SCHEMA.md).

### Chunking — per-exchange, length-gated

- Unit = **exchange**: a user message plus the agent/tool activity until the
  next user message.
- Record granularity = per-message; embedding granularity = per-exchange.
- Length gate (configurable token cap): exchange ≤ cap → embed verbatim;
  exchange > cap → summarize with a cheap model, then embed the summary.

### Retrieval

`session-search "query"` → embed the query locally → sqlite-vec KNN over chunk
vectors + FTS5 BM25 over scrubbed-verbatim records → reciprocal-rank-fusion →
return summaries plus a pointer back to the full L0 context. No daemon, no
server — a CLI invoked directly (e.g. from an agent's shell tool).

## Build vs adopt

Adopted for the embedding layer: [`simonw/llm`](https://github.com/simonw/llm)
\+ [`llm-embed-onnx`](https://github.com/simonw/llm-embed-onnx) +
[`sqlite-vec`](https://github.com/asg017/sqlite-vec) (local ONNX all-MiniLM).
Custom-built: the connector + canonical schema, length-gated per-exchange
chunking, embeddings-as-git-jsonl export, the FTS5+vec RRF CLI, and the secret
scrub gate — none of which exist off the shelf.

## Status

| Milestone | State |
|---|---|
| Canonical schema + Claude Code connector (full-turn) | planned |
| Length-gated chunker + summary + embedding | planned |
| sqlite rebuild (FTS5 + vec) + `session-search` CLI (RRF) | planned |
| Idempotent batch ingest (cron/manual) + `render-md` | planned |

## License

[MIT](LICENSE).
