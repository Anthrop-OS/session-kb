"""Chunker tests — synthetic turns only (never real content).

Exercises the raw path end-to-end plus the injected-summarizer branch for
over-cap exchanges. No model or .jsonl is involved.
"""

import hashlib
import json

import pytest

from session_kb.chunker import chunk
from session_kb.connectors import claude_code as cc
from session_kb.schema import RawPtr, Source, TurnRecord

SESSION = "chunk-synthetic"


def _sha(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _turn(seq, exchange_n, actor, message, *, session=SESSION):
    """Minimal valid TurnRecord for chunker unit tests."""
    return TurnRecord(
        session_id=session,
        seq=seq,
        exchange_id=f"{session}:x{exchange_n}",
        actor=actor,
        message=message,
        content_hash=_sha(message),
        source=Source(harness="claude-code", connector_version="0.1.0", provider="anthropic"),
        raw_ptr=RawPtr(uuids=[f"u{seq}"]),
        ts="2026-01-01T00:00:00Z",
    )


def test_single_exchange_raw_chunk():
    turns = [
        _turn(1, 1, "user", "deploy the service"),
        _turn(2, 1, "agent", "on it"),
        _turn(3, 1, "tool", "exit 0"),
    ]
    (c,) = list(chunk(turns))
    assert c.exchange_id == f"{SESSION}:x1"
    assert c.session_id == SESSION
    assert c.embed_source == "raw"
    assert c.summary is None
    expected = "user: deploy the service\n\nagent: on it\n\ntool: exit 0"
    assert c.content_hash == _sha(expected)


def test_one_chunk_per_exchange_in_order():
    turns = [
        _turn(1, 1, "user", "first ask"),
        _turn(2, 1, "agent", "first answer"),
        _turn(3, 2, "user", "second ask"),
        _turn(4, 2, "agent", "second answer"),
        _turn(5, 3, "user", "third ask"),
    ]
    chunks = list(chunk(turns))
    assert [c.exchange_id for c in chunks] == [f"{SESSION}:x{n}" for n in (1, 2, 3)]
    assert all(c.embed_source == "raw" for c in chunks)


def test_empty_message_turns_are_dropped_from_embed_text():
    # a pure tool_use agent turn carries no text → must not emit a bare "agent:" line
    turns = [
        _turn(1, 1, "user", "run it"),
        _turn(2, 1, "agent", "   "),  # whitespace-only
        _turn(3, 1, "tool", "done"),
    ]
    (c,) = list(chunk(turns))
    assert c.content_hash == _sha("user: run it\n\ntool: done")


def test_over_cap_without_summarizer_raises():
    big = "x" * 9000  # ~2250 tokens > default 2048 cap
    turns = [_turn(1, 1, "user", big)]
    with pytest.raises(NotImplementedError, match="summarizer="):
        list(chunk(turns))


def test_over_cap_with_summarizer_embeds_summary():
    big = "y" * 9000
    turns = [_turn(1, 1, "user", big)]
    (c,) = list(chunk(turns, summarizer=lambda text: "SUMMARY"))
    assert c.embed_source == "summary"
    assert c.summary == "SUMMARY"
    assert c.content_hash == _sha("SUMMARY")  # hash tracks the embedded summary, not the raw


def test_threshold_is_configurable():
    turns = [_turn(1, 1, "user", "a moderately sized prompt that is small")]
    # force the over-cap branch with a tiny threshold; injected summarizer handles it
    (c,) = list(chunk(turns, summary_threshold_tokens=1, summarizer=lambda t: "S"))
    assert c.embed_source == "summary"


def test_no_turns_yields_no_chunks():
    assert list(chunk([])) == []


def test_integration_through_connector(tmp_path):
    """Group real connector output: user + agent(tool_use) + tool_result = 1 exchange."""
    entries = [
        {
            "type": "user",
            "uuid": "u1",
            "sessionId": SESSION,
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {"role": "user", "content": "list files"},
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
                    {"type": "text", "text": "running ls"},
                    {"type": "tool_use", "id": "tc1", "name": "Bash", "input": {"command": "ls"}},
                ],
            },
        },
        {
            "type": "user",
            "uuid": "u3",
            "parentUuid": "u2",
            "sessionId": SESSION,
            "timestamp": "2026-01-01T00:00:02Z",
            "toolUseResult": {"stdout": "a.txt"},
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tc1", "content": "a.txt"}],
            },
        },
        {
            "type": "user",
            "uuid": "u4",
            "parentUuid": "u3",
            "sessionId": SESSION,
            "timestamp": "2026-01-01T00:00:03Z",
            "message": {"role": "user", "content": "thanks"},
        },
    ]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    chunks = list(chunk(cc.iter_turns(path)))

    # two user boundaries → two exchanges; first bundles user+agent+tool
    assert [c.exchange_id for c in chunks] == [f"{SESSION}:x1", f"{SESSION}:x2"]
    assert chunks[0].content_hash == _sha("user: list files\n\nagent: running ls\n\ntool: a.txt")
    assert chunks[1].content_hash == _sha("user: thanks")
