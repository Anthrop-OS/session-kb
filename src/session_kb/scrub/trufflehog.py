"""Optional trufflehog wrapper — gracefully skipped if trufflehog is not installed."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .interface import Finding


def _trufflehog_available() -> bool:
    return shutil.which("trufflehog") is not None


class TrufflehogScrubProvider:
    """ScrubProvider backed by trufflehog CLI. No-op if trufflehog is not installed."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._available = _trufflehog_available()
        self._config = str(config_path) if config_path else None

    def scan(self, text: str) -> list[Finding]:
        if not self._available:
            return []

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            dir=tempfile.gettempdir(),
        ) as tmp:
            tmp.write(text)
            tmp_path = tmp.name

        try:
            cmd = ["trufflehog", "filesystem", tmp_path, "--json", "--no-update"]
            if self._config:
                cmd.extend(["--config", self._config])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            findings: list[Finding] = []
            # trufflehog emits NDJSON (one object per line), not a JSON array
            for line in result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                raw = r.get("Raw", "")
                if not raw:
                    continue
                idx = text.find(raw)
                if idx == -1:
                    continue
                findings.append(
                    Finding(
                        start=idx,
                        end=idx + len(raw),
                        type=f"trufflehog:{r.get('DetectorName', 'unknown')}",
                        value=raw,
                    )
                )
            return findings
        except (subprocess.TimeoutExpired, OSError):
            return []
        finally:
            Path(tmp_path).unlink(missing_ok=True)
