"""Smoke test for the canonical schema (synthetic data only — never real content)."""

from session_kb.schema import SCHEMA_VERSION, RawPtr, Source, TurnRecord


def test_turn_record_roundtrip():
    rec = TurnRecord(
        session_id="synthetic-session",
        turn=1,
        chunk_id="synthetic-session:t1",
        actor="user",
        message_type="raw",
        message="hello",
        source=Source(harness="claude-code", model="test", connector_version="0.0.0"),
        raw_ptr=RawPtr(span=(1, 1), uuids=["00000000-0000-0000-0000-000000000000"]),
        ts="2026-01-01T00:00:00Z",
    )
    assert rec.schema_version == SCHEMA_VERSION
    assert rec.actor == "user"
    assert rec.redacted is False
