"""Ingest spine tests — synthetic transcripts only (never real content).

The synthetic secret matches the builtin provider's *generic-api-key* rule (a
``token_`` prefix + 32+ chars) — deliberately NOT a provider partner-pattern, so
it exercises the scrub without tripping GitHub push protection. Clearly marked
SYNTHETIC/fake so it is never mistaken for a real credential.
"""

import hashlib
import json

from session_kb import ingest
from session_kb.connectors import claude_code as cc
from session_kb.scrub import BuiltinScrubProvider

SESSION = "ingest-synthetic"
# generic-api-key shape → caught by the builtin provider; not a real credential.
SECRET = "token_SYNTHETICfake0000111122223333aaaabbbb"


def _write(tmp_path, entries):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


def _transcript(tmp_path):
    entries = [
        {
            "type": "user",
            "uuid": "u1",
            "parentUuid": None,
            "sessionId": SESSION,
            "cwd": "/repo",
            "gitBranch": "main",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {"role": "user", "content": f"deploy with {SECRET} please"},
        },
        {
            "type": "assistant",
            "uuid": "u2",
            "parentUuid": "u1",
            "sessionId": SESSION,
            "timestamp": "2026-01-01T00:00:01Z",
            "message": {
                "role": "assistant",
                "model": "claude-x",
                "content": [
                    {"type": "text", "text": "running it"},
                    {
                        "type": "tool_use",
                        "id": "tc1",
                        "name": "Bash",
                        "input": {"command": f"curl -H token:{SECRET}"},
                    },
                ],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            },
        },
        {
            "type": "user",
            "uuid": "u3",
            "parentUuid": "u2",
            "sessionId": SESSION,
            "timestamp": "2026-01-01T00:00:02Z",
            "toolUseResult": {"stdout": f"authorized with {SECRET}", "log": [f"used {SECRET}"]},
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tc1", "content": "ok"}],
            },
        },
    ]
    return _write(tmp_path, entries)


def test_ingest_writes_l1(tmp_path):
    path = _transcript(tmp_path)
    out = tmp_path / "data-repo"
    rc = ingest.run([str(path), "--host", "tp-server", "--out", str(out)])
    assert rc == 0

    sessions_file = out / "l1" / "sessions.jsonl"
    turns_file = out / "l1" / "turns" / f"{SESSION}.jsonl"
    assert sessions_file.exists() and turns_file.exists()

    sessions = [json.loads(line) for line in sessions_file.read_text().splitlines()]
    assert len(sessions) == 1
    assert sessions[0]["host"] == "tp-server"
    assert sessions[0]["turn_count"] == 3

    turns = [json.loads(line) for line in turns_file.read_text().splitlines()]
    assert len(turns) == 3
    assert [t["actor"] for t in turns] == ["user", "agent", "tool"]


def test_secret_is_scrubbed_everywhere_before_write(tmp_path):
    path = _transcript(tmp_path)
    out = tmp_path / "data-repo"
    ingest.run([str(path), "--host", "h", "--out", str(out)])

    # The raw secret must appear in NO written file; tokens take its place.
    written = "".join(p.read_text() for p in (out / "l1").rglob("*.jsonl"))
    assert SECRET not in written
    assert "<CRED:" in written  # message, tool_calls.arguments, and ext were all redacted


def test_content_hash_tracks_scrubbed_message(tmp_path):
    path = _transcript(tmp_path)
    out = tmp_path / "data-repo"
    ingest.run([str(path), "--host", "h", "--out", str(out)])
    turns = [
        json.loads(line)
        for line in (out / "l1" / "turns" / f"{SESSION}.jsonl").read_text().splitlines()
    ]
    user = turns[0]
    assert user["redacted"] is True
    assert user["scrub_rules_version"] == ingest.SCRUB_RULES_VERSION
    expected = "sha256:" + hashlib.sha256(user["message"].encode()).hexdigest()
    assert user["content_hash"] == expected
    assert SECRET not in user["message"]


def test_ingest_is_idempotent(tmp_path):
    path = _transcript(tmp_path)
    out = tmp_path / "data-repo"
    ingest.run([str(path), "--host", "h", "--out", str(out)])
    first = {p.name: p.read_bytes() for p in (out / "l1").rglob("*.jsonl")}
    ingest.run([str(path), "--host", "h", "--out", str(out)])
    second = {p.name: p.read_bytes() for p in (out / "l1").rglob("*.jsonl")}
    assert first == second  # re-run rewrites in place, byte-identical


def test_two_sessions_share_manifest_one_turns_file_each(tmp_path):
    out = tmp_path / "data-repo"
    p1 = _transcript(tmp_path)
    other = tmp_path / "other.jsonl"
    other.write_text(
        json.dumps(
            {
                "type": "user",
                "uuid": "z1",
                "sessionId": "other-session",
                "timestamp": "2026-01-02T00:00:00Z",
                "message": {"role": "user", "content": "clean prompt"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ingest.run([str(p1), str(other), "--host", "h", "--out", str(out)])
    sessions = [
        json.loads(line) for line in (out / "l1" / "sessions.jsonl").read_text().splitlines()
    ]
    assert {s["session_id"] for s in sessions} == {SESSION, "other-session"}
    assert (out / "l1" / "turns" / f"{SESSION}.jsonl").exists()
    assert (out / "l1" / "turns" / "other-session.jsonl").exists()


def test_empty_transcript_is_skipped(tmp_path, capsys):
    out = tmp_path / "data-repo"
    path = _write(tmp_path, [{"type": "attachment", "sessionId": SESSION}])
    rc = ingest.run([str(path), "--host", "h", "--out", str(out)])
    assert rc == 0
    assert "skip" in capsys.readouterr().out
    assert not (out / "l1").exists()


def test_scrub_turn_unit_clean_vs_secret(tmp_path):
    provider = BuiltinScrubProvider()
    path = _transcript(tmp_path)
    turns = list(cc.iter_turns(path))
    # the user turn carries the secret → redacted; hash changes from the verbatim one
    scrubbed = ingest.scrub_turn(turns[0], provider)
    assert scrubbed.redacted is True
    assert SECRET not in scrubbed.message
    assert scrubbed.content_hash != turns[0].content_hash


def test_scrub_turn_no_findings_keeps_hash(tmp_path):
    provider = BuiltinScrubProvider()
    other = tmp_path / "clean.jsonl"
    other.write_text(
        json.dumps(
            {
                "type": "user",
                "uuid": "c1",
                "sessionId": "s",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"role": "user", "content": "just a clean prompt"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    turn = next(cc.iter_turns(other))
    scrubbed = ingest.scrub_turn(turn, provider)
    assert scrubbed.redacted is False
    assert scrubbed.content_hash == turn.content_hash  # message unchanged
    assert scrubbed.scrub_rules_version == ingest.SCRUB_RULES_VERSION
