"""Tests for the scrub module — synthetic data only."""

from __future__ import annotations

import textwrap

import pytest

from session_kb.scrub.builtin import BuiltinScrubProvider
from session_kb.scrub.composite import CompositeScrubProvider
from session_kb.scrub.interface import Finding, ScrubProvider, redact, tokenize


# ---------------------------------------------------------------------------
# interface: tokenize + redact
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_deterministic(self):
        f = Finding(start=0, end=5, type="test", value="hello")
        assert tokenize(f) == tokenize(f)

    def test_format(self):
        f = Finding(start=0, end=5, type="test", value="hello")
        tok = tokenize(f)
        assert tok.startswith("<CRED:test:")
        assert tok.endswith(">")
        # sha256 prefix is 12 hex chars
        prefix = tok.split(":")[2].rstrip(">")
        assert len(prefix) == 12

    def test_different_values_different_tokens(self):
        f1 = Finding(start=0, end=1, type="t", value="aaa")
        f2 = Finding(start=0, end=1, type="t", value="bbb")
        assert tokenize(f1) != tokenize(f2)


class TestRedact:
    def test_single_finding(self):
        text = "key is sk-live-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHH here"
        f = Finding(start=7, end=47, type="api", value=text[7:47])
        result = redact(text, [f])
        assert "sk-live" not in result
        assert "<CRED:api:" in result
        assert result.startswith("key is ")
        assert result.endswith(" here")

    def test_multiple_findings_no_overlap(self):
        text = "a]SECRET1[b]SECRET2[c"
        findings = [
            Finding(start=2, end=9, type="x", value="SECRET1"),
            Finding(start=12, end=19, type="y", value="SECRET2"),
        ]
        result = redact(text, findings)
        assert "SECRET1" not in result
        assert "SECRET2" not in result

    def test_empty_findings(self):
        text = "nothing secret here"
        assert redact(text, []) == text


# ---------------------------------------------------------------------------
# builtin: batteries-included patterns + entropy
# ---------------------------------------------------------------------------


class TestBuiltinProvider:
    @pytest.fixture()
    def scrubber(self):
        return BuiltinScrubProvider()

    def test_catches_aws_key(self, scrubber):
        text = "aws_key = AKIAIOSFODNN7EXAMPLE"
        findings = scrubber.scan(text)
        types = {f.type for f in findings}
        assert "aws-access-key" in types

    def test_catches_github_pat_classic(self, scrubber):
        text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijij"
        findings = scrubber.scan(text)
        types = {f.type for f in findings}
        assert "github-pat-classic" in types

    def test_catches_generic_api_key(self, scrubber):
        text = "SYNTH_API_KEY=sk-synth-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        findings = scrubber.scan(text)
        assert len(findings) > 0, "must catch sk-* pattern"

    def test_catches_jwt(self, scrubber):
        header = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        payload = "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
        sig = "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        text = f"Bearer {header}.{payload}.{sig}"
        findings = scrubber.scan(text)
        types = {f.type for f in findings}
        assert "jwt" in types

    def test_catches_pem_header(self, scrubber):
        text = "-----BEGIN RSA PRIVATE KEY-----\nfakedata\n-----END RSA PRIVATE KEY-----"
        findings = scrubber.scan(text)
        types = {f.type for f in findings}
        assert "pem-private-key" in types

    def test_catches_high_entropy(self, scrubber):
        # 40 random-looking chars that don't match any pattern prefix
        high_entropy = "Xq9mR7kL2pN4vB8wZ5jT3fH6dA0sY1cG7eU"
        text = f"secret = {high_entropy}"
        findings = scrubber.scan(text)
        entropy_findings = [f for f in findings if f.type == "high-entropy"]
        assert len(entropy_findings) > 0, "must catch high-entropy strings"

    def test_passes_clean_text(self, scrubber):
        text = "Fix the auth middleware to validate JWT tokens properly"
        findings = scrubber.scan(text)
        assert len(findings) == 0

    def test_passes_normal_code(self, scrubber):
        text = textwrap.dedent("""\
            def validate_token(token: str) -> bool:
                if not token:
                    return False
                return check_signature(token)
        """)
        findings = scrubber.scan(text)
        assert len(findings) == 0

    def test_redact_deterministic(self, scrubber):
        text = "key is sk-synth-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA here"
        r1 = scrubber.redact(text)
        r2 = scrubber.redact(text)
        assert r1 == r2
        assert "sk-synth" not in r1
        assert "<CRED:" in r1


# ---------------------------------------------------------------------------
# composite: union of multiple providers
# ---------------------------------------------------------------------------


class TestCompositeProvider:
    def test_unions_findings(self):
        class ProviderA:
            def scan(self, text: str) -> list[Finding]:
                return [Finding(start=0, end=4, type="a", value=text[0:4])] if len(text) > 4 else []

        class ProviderB:
            def scan(self, text: str) -> list[Finding]:
                return [Finding(start=5, end=9, type="b", value=text[5:9])] if len(text) > 9 else []

        comp = CompositeScrubProvider([ProviderA(), ProviderB()])
        findings = comp.scan("0123456789abcdef")
        types = {f.type for f in findings}
        assert types == {"a", "b"}

    def test_deduplicates_same_span(self):
        class SameSpan:
            def scan(self, text: str) -> list[Finding]:
                return [Finding(start=0, end=5, type="dup", value="hello")]

        comp = CompositeScrubProvider([SameSpan(), SameSpan()])
        findings = comp.scan("hello world")
        assert len(findings) == 1

    def test_builtin_always_runs(self):
        comp = CompositeScrubProvider([BuiltinScrubProvider()])
        text = "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        findings = comp.scan(text)
        assert len(findings) > 0

    def test_custom_provider_extends_builtin(self):
        class CustomProvider:
            def scan(self, text: str) -> list[Finding]:
                if "CUSTOM_TRAP" in text:
                    idx = text.index("CUSTOM_TRAP")
                    return [Finding(start=idx, end=idx + 11, type="custom", value="CUSTOM_TRAP")]
                return []

        comp = CompositeScrubProvider([BuiltinScrubProvider(), CustomProvider()])
        text = "has CUSTOM_TRAP and sk-synth-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        findings = comp.scan(text)
        types = {f.type for f in findings}
        assert "custom" in types
        assert len(findings) >= 2

    def test_protocol_check(self):
        assert isinstance(BuiltinScrubProvider(), ScrubProvider)


# ---------------------------------------------------------------------------
# extra-patterns: YAML file loader
# ---------------------------------------------------------------------------


class TestExtraPatterns:
    def test_loads_yaml_file(self, tmp_path):
        pytest.importorskip("yaml")
        from session_kb.scrub.patterns import ExtraPatternsScrubProvider

        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(
            textwrap.dedent("""\
            patterns:
              - id: synth-internal
                regex: "SYNTH_INTERNAL_[A-Z]{10}"
        """)
        )

        provider = ExtraPatternsScrubProvider(patterns_file)
        findings = provider.scan("key = SYNTH_INTERNAL_ABCDEFGHIJ")
        assert len(findings) == 1
        assert findings[0].type == "extra:synth-internal"

    def test_no_match_returns_empty(self, tmp_path):
        pytest.importorskip("yaml")
        from session_kb.scrub.patterns import ExtraPatternsScrubProvider

        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text("patterns:\n  - id: nope\n    regex: 'WONTMATCH'\n")

        provider = ExtraPatternsScrubProvider(patterns_file)
        findings = provider.scan("nothing matches here")
        assert len(findings) == 0

    def test_composite_with_extra_patterns(self, tmp_path):
        pytest.importorskip("yaml")
        from session_kb.scrub.patterns import ExtraPatternsScrubProvider

        patterns_file = tmp_path / "patterns.yaml"
        patterns_file.write_text(
            textwrap.dedent("""\
            patterns:
              - id: private-svc
                regex: "svc_tok_[a-f0-9]{32}"
        """)
        )

        comp = CompositeScrubProvider(
            [
                BuiltinScrubProvider(),
                ExtraPatternsScrubProvider(patterns_file),
            ]
        )
        text = (
            "svc_tok_deadbeef1234567890abcdef12345678 and ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        )
        findings = comp.scan(text)
        types = {f.type for f in findings}
        assert "extra:private-svc" in types
        assert "github-pat-classic" in types


# ---------------------------------------------------------------------------
# gitleaks / trufflehog: graceful skip when not installed
# ---------------------------------------------------------------------------


class TestExternalToolGracefulSkip:
    def test_gitleaks_no_op_when_missing(self):
        from session_kb.scrub.gitleaks import GitleaksScrubProvider

        provider = GitleaksScrubProvider()
        # should not raise, should return empty if gitleaks not on PATH
        findings = provider.scan("AKIAIOSFODNN7EXAMPLE")
        # we can't assert findings > 0 if gitleaks isn't installed
        assert isinstance(findings, list)

    def test_trufflehog_no_op_when_missing(self):
        from session_kb.scrub.trufflehog import TrufflehogScrubProvider

        provider = TrufflehogScrubProvider()
        findings = provider.scan("AKIAIOSFODNN7EXAMPLE")
        assert isinstance(findings, list)
