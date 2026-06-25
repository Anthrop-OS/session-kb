"""Idempotent batch ingest: connector → scrub → L1 records.

The pipeline spine. For each native transcript:

    connector  →  scrub  →  write L1 (sessions.jsonl + turns/<sid>.jsonl)
                            └─ (chunk → embed: later milestones)

Decoupled from session lifecycle (cron / manual). **Idempotent**: re-running a
session rewrites that session's records in place (a re-derive), never appends
duplicates — so a scrub-logic change is just a re-run. A mandatory secret scrub
runs before any write to the L1 git repo (the security boundary is L0 encryption;
scrub reduces magnitude — but it still runs on everything that lands in L1).

The scrub stage covers every secret-bearing field, not just ``message``: it also
deep-scrubs ``ext`` (raw native payloads like ``toolUseResult``) and each
``tool_calls.arguments`` blob, then recomputes ``content_hash`` so it always
matches the stored (scrubbed) message.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .connectors import claude_code
from .schema import SessionRecord, TurnRecord
from .scrub import BuiltinScrubProvider
from .scrub.interface import ScrubProvider, redact

SCRUB_RULES_VERSION = "builtin-1"

# session-constant string fields worth a defensive scrub (paths can leak tokens).
_SESSION_STR_FIELDS = ("cwd", "workspace", "project", "git_branch")


def _content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- scrub stage -----------------------------------------------------------


def _scrub_text(text: str, provider: ScrubProvider) -> tuple[str, bool]:
    findings = provider.scan(text)
    if not findings:
        return text, False
    return redact(text, findings), True


def _scrub_json(value: Any, provider: ScrubProvider) -> tuple[Any, bool]:
    """Recursively redact every string leaf in a JSON-ish value."""
    if isinstance(value, str):
        return _scrub_text(value, provider)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        redacted = False
        for key, item in value.items():
            out[key], item_redacted = _scrub_json(item, provider)
            redacted = redacted or item_redacted
        return out, redacted
    if isinstance(value, list):
        out_list: list[Any] = []
        redacted = False
        for item in value:
            scrubbed, item_redacted = _scrub_json(item, provider)
            out_list.append(scrubbed)
            redacted = redacted or item_redacted
        return out_list, redacted
    return value, False


def scrub_turn(
    turn: TurnRecord, provider: ScrubProvider, rules_version: str = SCRUB_RULES_VERSION
) -> TurnRecord:
    """Redact a turn's message + ext + tool_call arguments; recompute content_hash."""
    message, msg_redacted = _scrub_text(turn.message, provider)
    ext, ext_redacted = _scrub_json(turn.ext, provider)

    tool_calls = []
    calls_redacted = False
    for call in turn.tool_calls:
        arguments, call_redacted = _scrub_json(call.arguments, provider)
        calls_redacted = calls_redacted or call_redacted
        tool_calls.append(call.model_copy(update={"arguments": arguments}))

    return turn.model_copy(
        update={
            "message": message,
            "content_hash": _content_hash(message),
            "ext": ext,
            "tool_calls": tool_calls,
            "redacted": msg_redacted or ext_redacted or calls_redacted,
            "scrub_rules_version": rules_version,
        }
    )


def scrub_session(session: SessionRecord, provider: ScrubProvider) -> SessionRecord:
    """Defensively scrub the manifest's free-text metadata fields."""
    updates: dict[str, Any] = {}
    for field in _SESSION_STR_FIELDS:
        value = getattr(session, field)
        if isinstance(value, str):
            scrubbed, redacted = _scrub_text(value, provider)
            if redacted:
                updates[field] = scrubbed
    return session.model_copy(update=updates) if updates else session


# --- L1 write (idempotent per session) -------------------------------------


def _record_json(record: SessionRecord | TurnRecord) -> dict[str, Any]:
    return json.loads(record.model_dump_json())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
    path.write_text(body, encoding="utf-8")


def write_l1(out_dir: Path, session: SessionRecord, turns: list[TurnRecord]) -> tuple[Path, Path]:
    """Upsert the session manifest line and rewrite this session's turns file."""
    l1 = Path(out_dir) / "l1"

    sessions_file = l1 / "sessions.jsonl"
    rows = [s for s in _read_jsonl(sessions_file) if s.get("session_id") != session.session_id]
    rows.append(_record_json(session))
    rows.sort(key=lambda s: s.get("session_id", ""))
    _write_jsonl(sessions_file, rows)

    turns_file = l1 / "turns" / f"{session.session_id}.jsonl"
    _write_jsonl(turns_file, [_record_json(t) for t in turns])
    return sessions_file, turns_file


# --- CLI -------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="session-ingest",
        description="connector → scrub → L1 records (idempotent per session).",
    )
    parser.add_argument("paths", nargs="+", type=Path, help="native session transcript paths")
    parser.add_argument("--host", required=True, help="canonical host the sessions ran on")
    parser.add_argument("--out", required=True, type=Path, help="L1 data-repo root")
    parser.add_argument(
        "--scrub-rules-version", default=SCRUB_RULES_VERSION, help="recorded on every turn"
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    provider = BuiltinScrubProvider()

    total_turns = total_redacted = sessions = 0
    for path in args.paths:
        try:
            session = claude_code.read_session(path, host=args.host)
        except ValueError as exc:
            print(f"skip {path}: {exc}")
            continue
        session = scrub_session(session, provider)
        turns = [
            scrub_turn(t, provider, args.scrub_rules_version) for t in claude_code.iter_turns(path)
        ]
        write_l1(args.out, session, turns)

        redacted = sum(1 for t in turns if t.redacted)
        sessions += 1
        total_turns += len(turns)
        total_redacted += redacted
        print(f"{session.session_id}: {len(turns)} turns ({redacted} redacted) → {args.out}/l1")

    print(f"done: {sessions} session(s), {total_turns} turns, {total_redacted} redacted")
    return 0


def main() -> int:  # pragma: no cover - thin CLI entrypoint
    return run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
