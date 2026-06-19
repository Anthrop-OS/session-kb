"""Optional gitleaks wrapper — gracefully skipped if gitleaks is not installed."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .interface import Finding


def _gitleaks_available() -> bool:
    return shutil.which("gitleaks") is not None


class GitleaksScrubProvider:
    """ScrubProvider backed by gitleaks CLI. No-op if gitleaks is not installed."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._available = _gitleaks_available()
        self._config = str(config_path) if config_path else None

    def scan(self, text: str) -> list[Finding]:
        if not self._available:
            return []

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
            tmp.write(text)
            tmp_path = tmp.name

        try:
            cmd = [
                "gitleaks", "dir", tmp_path,
                "--no-git",
                "--report-format", "json",
                "--report-path", "/dev/stdout",
            ]
            if self._config:
                cmd.extend(["--config", self._config])

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            # gitleaks exits 1 when findings exist, 0 when clean
            output = result.stdout.strip()
            if not output:
                return []

            raw_findings = json.loads(output)
            findings: list[Finding] = []
            for r in raw_findings:
                secret = r.get("Secret", "")
                idx = text.find(secret)
                if idx == -1:
                    continue
                findings.append(Finding(
                    start=idx,
                    end=idx + len(secret),
                    type=f"gitleaks:{r.get('RuleID', 'unknown')}",
                    value=secret,
                ))
            return findings
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            return []
        finally:
            Path(tmp_path).unlink(missing_ok=True)
