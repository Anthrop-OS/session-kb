# Extra patterns — extending the secret scrub

session-kb ships a batteries-included builtin scrub (entropy detection +
standard secret patterns). Two extension mechanisms let you add coverage
without forking the tool.

## 1. `--extra-patterns` (YAML file)

Write a YAML file with custom regex patterns:

```yaml
# my-patterns.yaml
patterns:
  - id: my-internal-token
    regex: "myapp_tok_[A-Za-z0-9]{40}"
  - id: staging-api-key
    regex: "STAGING-[A-F0-9]{32}"
```

Pass it to ingest:

```bash
session-ingest --extra-patterns my-patterns.yaml ~/.claude/projects/*/
```

Each match is tokenized as `<CRED:extra:my-internal-token:sha256-prefix>`.
The YAML file itself should be kept private (it reveals what credential
types you use).

Requires PyYAML: `pip install pyyaml`.

## 2. External tools (gitleaks / trufflehog)

If `gitleaks` or `trufflehog` is on `$PATH`, session-kb can use them as
additional scrub providers. They run automatically when available — no
configuration needed for default rules.

```bash
# install (optional — builtin scrub works without them)
brew install gitleaks
brew install trufflehog

# ingest picks them up automatically
session-ingest ~/.claude/projects/*/
```

To pass a custom gitleaks config or trufflehog detector file:

```bash
session-ingest \
  --gitleaks-config gitleaks.toml \
  --trufflehog-config detectors.yaml \
  ~/.claude/projects/*/
```

## 3. Programmatic (ScrubProvider protocol)

Implement the `ScrubProvider` protocol for full control:

```python
from session_kb.scrub import Finding, ScrubProvider, CompositeScrubProvider, BuiltinScrubProvider

class MyScrubProvider:
    def scan(self, text: str) -> list[Finding]:
        findings = []
        # your detection logic here
        return findings

# compose with builtin
scrubber = CompositeScrubProvider([BuiltinScrubProvider(), MyScrubProvider()])
findings = scrubber.scan("text with my_secret_value")
```

The composite unions all findings (deduplicated by span). Builtin always
runs — extra providers add coverage, they never replace the baseline.

## Design notes

- **Scrub is not the security boundary** — it reduces magnitude. The real
  boundary is L0 encryption (restic/age). Treat scrub misses as expected;
  the encrypted layer catches what scrub doesn't.
- **Tokenization is deterministic**: same secret value → same
  `<CRED:type:hash>` token across sessions. This preserves cross-session
  correlation in analytics without retaining the original value.
- **Builtin patterns are public knowledge** — sourced from gitleaks and
  trufflehog open-source rule sets. Your `--extra-patterns` file is the
  private part; keep it out of public repos.
