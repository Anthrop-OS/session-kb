"""Claude Code connector tests — synthetic transcripts only (never real content).

Fixtures are written to a tmp jsonl at runtime; no .jsonl is ever committed (the
repo's content-free guard rejects committed jsonl).
"""

import json

import pytest

from session_kb.connectors import claude_code as cc
from session_kb.schema import SessionRecord, ToolCall, TurnRecord

SESSION = "synthetic-session"


def _user(uuid, text, ts, parent=None):
    return {
        "type": "user",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": SESSION,
        "cwd": "/repo/sub",
        "gitBranch": "main",
        "timestamp": ts,
        "isSidechain": False,
        "version": "1.0.0",
        "message": {"role": "user", "content": text},
    }


def _assistant(uuid, blocks, ts, parent, model="claude-x", usage=None):
    return {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": SESSION,
        "cwd": "/repo/sub",
        "gitBranch": "main",
        "timestamp": ts,
        "requestId": "req-1",
        "version": "1.0.0",
        "message": {
            "role": "assistant",
            "model": model,
            "content": blocks,
            "usage": usage or {"input_tokens": 10, "output_tokens": 5},
        },
    }


def _tool_result(uuid, tool_use_id, text, ts, parent):
    return {
        "type": "user",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": SESSION,
        "timestamp": ts,
        "toolUseResult": {"stdout": text},
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": text}],
        },
    }


def _write(tmp_path, entries):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def transcript(tmp_path):
    entries = [
        _user("u1", "hello", "2026-01-01T00:00:00Z"),
        _assistant(
            "u2",
            [
                {"type": "text", "text": "hi"},
                {"type": "tool_use", "id": "tc1", "name": "Read", "input": {"file": "x"}},
            ],
            "2026-01-01T00:00:01Z",
            parent="u1",
        ),
        _tool_result("u3", "tc1", "file body", "2026-01-01T00:00:02Z", parent="u2"),
        _assistant("u4", [{"type": "text", "text": "done"}], "2026-01-01T00:00:03Z", parent="u3"),
        {"type": "attachment", "uuid": "a1", "sessionId": SESSION},  # skipped
        _user("u5", "next question", "2026-01-01T00:00:04Z", parent="u4"),
    ]
    return _write(tmp_path, entries)


def test_actors_and_exchange_boundaries(transcript):
    turns = list(cc.iter_turns(transcript))
    assert [t.actor for t in turns] == ["user", "agent", "tool", "agent", "user"]
    # the attachment line is dropped; seq is dense and monotonic
    assert [t.seq for t in turns] == [1, 2, 3, 4, 5]
    # one exchange spans the first user + its agent/tool turns; the 2nd user opens x2
    assert [t.exchange_id for t in turns] == [
        f"{SESSION}:x1",
        f"{SESSION}:x1",
        f"{SESSION}:x1",
        f"{SESSION}:x1",
        f"{SESSION}:x2",
    ]


def test_records_are_valid_turn_records(transcript):
    turns = list(cc.iter_turns(transcript))
    assert all(isinstance(t, TurnRecord) for t in turns)


def test_tool_use_becomes_typed_tool_calls(transcript):
    agent = list(cc.iter_turns(transcript))[1]
    assert agent.actor == "agent"
    assert agent.tool_calls == [ToolCall(id="tc1", name="Read", arguments={"file": "x"})]
    assert agent.input_tokens == 10
    assert agent.output_tokens == 5
    assert agent.source.model == "claude-x"


def test_tool_result_pairs_and_carries_native_payload(transcript):
    tool = list(cc.iter_turns(transcript))[2]
    assert tool.actor == "tool"
    assert tool.tool_call_id == "tc1"
    assert tool.message == "file body"
    assert tool.ext["claude_code"]["tool_use_result"] == {"stdout": "file body"}


def test_content_hash_matches_message(transcript):
    user = list(cc.iter_turns(transcript))[0]
    assert user.content_hash == cc._content_hash("hello")
    assert user.ext["claude_code"] == {"is_sidechain": False, "version": "1.0.0"}
    assert user.parent_id is None  # null parentUuid is dropped, not stored


def test_read_session_manifest(transcript):
    session = cc.read_session(transcript, host="tp-server")
    assert isinstance(session, SessionRecord)
    assert session.host == "tp-server"
    assert session.started_at == "2026-01-01T00:00:00Z"
    assert session.ended_at == "2026-01-01T00:00:04Z"
    assert session.turn_count == 5
    assert session.cursor == "u5"  # last native id = incremental anchor
    assert session.source.model == "claude-x"


def test_transcript_opening_with_assistant_anchors_exchange(tmp_path):
    # a resumed/compacted transcript can open mid-exchange (no leading user line)
    path = _write(
        tmp_path,
        [
            _assistant(
                "u1", [{"type": "text", "text": "resumed"}], "2026-01-01T00:00:00Z", parent=None
            )
        ],
    )
    turns = list(cc.iter_turns(path))
    assert turns[0].exchange_id == f"{SESSION}:x1"


def test_string_and_unknown_content_flatten(tmp_path):
    path = _write(
        tmp_path,
        [
            _user("u1", "plain string", "2026-01-01T00:00:00Z"),
            _assistant("u2", None, "2026-01-01T00:00:01Z", parent="u1"),
        ],
    )
    turns = list(cc.iter_turns(path))
    assert turns[0].message == "plain string"  # string content flattens to itself
    assert turns[1].message == ""  # non-str / non-list content flattens to empty


def test_empty_transcript_raises(tmp_path):
    path = _write(tmp_path, [{"type": "attachment", "sessionId": SESSION}])
    with pytest.raises(ValueError):
        cc.read_session(path, host="tp-server")
