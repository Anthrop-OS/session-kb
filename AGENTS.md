# AGENTS.md

Guidance for AI agents contributing to `session-kb`. (Human contributors: this
doubles as the contributor quick-reference.)

## What this repo is

Tool code for archiving and retrieving finished AI coding sessions. Pipeline:
connector → canonical turn records → chunk + embed → sqlite (FTS5 + vec),
queried by the `session-search` CLI. Read [README.md](README.md) for the design
and [docs/SCHEMA.md](docs/SCHEMA.md) for the record contract.

## Hard rules

1. **Never commit session content.** This is a public, content-free repo by
   construction. No transcripts, no summaries, no embeddings, no real keys, no
   personal data — not even as test fixtures. Use synthetic fixtures only.
2. **Scrub is not the security boundary; encryption is.** Treat the secret
   scrub as magnitude reduction, never as a guarantee. Never weaken it.
3. **Respect the layer invariants:** `L2 = f(L1)` and `L1 = f(L0)`. Derived
   layers must stay disposable and rebuildable; never make L2 a source of truth.
4. **Keep the connector contract harness-agnostic.** Don't bake Claude-Code
   specifics into shared code — they belong in `connectors/claude_code.py`.

## Layout

```
src/session_kb/
  schema.py            canonical turn + embedding records
  connectors/          per-harness native → canonical mappers
  scrub/               pluggable secret scrub (magnitude reduction, not boundary)
    interface.py       ScrubProvider protocol + Finding + tokenize + redact
    builtin.py         batteries-included: entropy + standard secret patterns
    gitleaks.py        optional gitleaks CLI wrapper (no-op if not installed)
    trufflehog.py      optional trufflehog CLI wrapper (no-op if not installed)
    patterns.py        --extra-patterns YAML loader → ScrubProvider
    composite.py       union multiple providers (deduplicated by span)
  chunker.py           per-exchange, length-gated
  embed.py             local ONNX all-MiniLM (llm-embed-onnx)
  index.py             sqlite FTS5 + vec build (L2 = f(L1))
  ingest.py            idempotent batch pipeline
  search.py            session-search CLI (RRF)
  init.py              session-kb-init: scaffold an L1 data repo from template
  templates/data_repo/ canonical skeleton for the private L1 data repo
docs/SCHEMA.md         the record contract
docs/EXTRA-PATTERNS.md --extra-patterns integration guide
tests/                 synthetic fixtures only
```

The tool repo owns the schema and layer model, so it also owns the **data-repo
template** (`templates/data_repo/`). `session-kb-init <dir>` materializes it —
this is how a new node/agent gets a consistent private L1 data repo. The data
repo itself never holds tool code; this repo never holds session content.

## Conventions

- Python ≥ 3.11, `ruff` (line length 100), `pytest`.
- Stubs raise `NotImplementedError("milestone: …")`; replace per milestone, keep
  the public signature stable.
- Embeddings are exported as jsonl and committed to the (separate, private) data
  repo — never to this repo. Index rebuild must require zero inference.

## Test & lint

```sh
pip install -e ".[dev]"
ruff check . && ruff format --check .
python scripts/gen_schema.py        # regenerate JSON Schema after ANY schema.py change
pytest                              # includes the schema drift-guard + coverage gate (≥90%)
```

If you touch `schema.py`, you **must** run `gen_schema.py` and commit the updated
`docs/schema/*.json` — a CI drift-guard test fails otherwise. Run all four steps
locally before pushing; they mirror CI exactly (lint / test matrix / content-free
guard / build), so a green local run means a green PR.

## Milestone PR workflow & traps

The pipeline lands one milestone per PR (stub → implementation, stable signature).
Two traps cost a round-trip if you don't know them up front:

1. **No committed `*.jsonl` — ever.** The content-free guard `find`s and rejects
   any committed jsonl (even synthetic). Connector / ingest fixtures must be
   written to a `tmp_path` at test runtime, never checked in. See
   `tests/test_connector_claude_code.py` for the pattern.
2. **GitHub push protection blocks provider-shaped synthetic secrets.** A fixture
   secret shaped like a real partner token (Slack `xox…`, AWS `AKIA…`, GitHub
   `ghp_…`) trips push protection and the push is *rejected* — do **not** click the
   unblock URL. Instead use a shape the builtin scrub catches but no provider
   claims: the **generic-api-key** rule (`token_` + 32+ chars). See
   `tests/test_ingest.py::SECRET`.

Verify a merged milestone end-to-end from a *clean* install (`pip install .`, run
the console entrypoint against a synthetic transcript), not just via `pytest` —
this catches packaging / entrypoint regressions the test suite can miss.
