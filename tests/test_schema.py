"""Smoke tests for the canonical schema (synthetic data only — never real content)."""

from session_kb.schema import (
    SCHEMA_VERSION,
    ChunkRecord,
    EmbeddingRecord,
    RawPtr,
    Source,
    TurnRecord,
)

SESSION = "synthetic-session"
EXCHANGE = f"{SESSION}:x1"


def test_turn_record_defaults():
    rec = TurnRecord(
        session_id=SESSION,
        seq=1,
        exchange_id=EXCHANGE,
        actor="user",
        message="hello",
        source=Source(harness="claude-code", connector_version="0.0.0"),
        raw_ptr=RawPtr(uuids=["00000000-0000-0000-0000-000000000000"]),
        ts="2026-01-01T00:00:00Z",
    )
    assert rec.record_type == "turn"
    assert rec.schema_version == SCHEMA_VERSION
    assert rec.actor == "user"
    assert rec.redacted is False
    assert rec.ext == {}
    assert rec.decisions == []


def test_tool_turn_carries_call_id():
    rec = TurnRecord(
        session_id=SESSION,
        seq=3,
        exchange_id=EXCHANGE,
        actor="tool",
        message="<tool output>",
        source=Source(harness="claude-code", connector_version="0.0.0"),
        raw_ptr=RawPtr(uuids=["11111111-1111-1111-1111-111111111111"]),
        ts="2026-01-01T00:00:02Z",
        tool_call_id="tc_1",
    )
    assert rec.tool_call_id == "tc_1"


def test_chunk_and_embedding_share_content_hash():
    h = "sha256:deadbeef"
    chunk = ChunkRecord(
        exchange_id=EXCHANGE,
        session_id=SESSION,
        embed_source="raw",
        content_hash=h,
    )
    emb = EmbeddingRecord(
        exchange_id=EXCHANGE,
        model="minilm-v2",
        dim=3,
        embedding=[0.0, 0.1, 0.2],
        content_hash=h,
    )
    assert chunk.record_type == "chunk"
    assert chunk.summary is None
    assert emb.record_type == "embedding"
    assert emb.dim == len(emb.embedding)
    assert chunk.content_hash == emb.content_hash


def test_summary_chunk_holds_text():
    chunk = ChunkRecord(
        exchange_id=EXCHANGE,
        session_id=SESSION,
        embed_source="summary",
        content_hash="sha256:cafe",
        summary="a synthetic summary of an over-cap exchange",
    )
    assert chunk.embed_source == "summary"
    assert chunk.summary is not None
