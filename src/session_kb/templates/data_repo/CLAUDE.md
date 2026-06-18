# CLAUDE.md

**Private** L1 data plane for `session-kb`. Read [README.md](README.md) first.

## Highest-priority rules

1. This repo is **private and must stay private** — it holds scrubbed session
   content.
2. **Never commit raw/unscrubbed transcripts or secret values.** Every record
   must carry `redacted: true` + a `scrub_rules_version`. Scrub is magnitude
   reduction, not the security boundary — L0 encryption is.
3. Raw bytes live in the encrypted L0 layer (out of band); records here point
   back via `raw_ptr`. Don't reconstruct raw here.
