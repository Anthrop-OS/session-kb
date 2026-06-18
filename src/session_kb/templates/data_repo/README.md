# L1 data repo

**Private** L1 data plane for [`session-kb`](https://github.com/Anthrop-OS/session-kb).
Scaffolded by `session-kb-init`.

This repository holds the **derived, scrubbed** layer of the session knowledge
base — never raw transcripts, never secret values.

## What lives here

`l1/` — derived records as jsonl, produced by the `session-kb` pipeline:

- scrubbed per-message turn records (canonical schema)
- per-exchange summaries
- embeddings (separate jsonl records)

Committing embeddings here is deliberate: an L2 index rebuild then needs **zero
inference** and is reproducible on any node.

## Layer model

```
L0 raw      full-fidelity, secret-tokenized, ENCRYPTED, append-only — out of band, NOT here
L1 derived  scrubbed records + summaries + embeddings (jsonl)        — THIS repo (private)
L2 index    sqlite FTS5 + sqlite-vec                                 — local, gitignored, rebuilt from L1
```

Invariants: `L2 = f(L1)`, `L1 = f(L0)`. This repo is re-derivable from L0 and is
itself the rebuild source for L2.

## Hard rules

- **Private repo. Never make public** — it contains scrubbed session content.
- **Never commit raw/unscrubbed transcripts or secret values.** Scrub
  (`redacted` + `scrub_rules_version` on every record) runs before any write.
  Scrub reduces magnitude; it is not the security boundary — L0 encryption is.
- A scrub-logic change means **re-deriving from L0**, never rewriting in place.
- Raw bytes stay in the encrypted L0 layer; records here point back via
  `raw_ptr`.
