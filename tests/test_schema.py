"""Smoke tests for the canonical schema (synthetic data only — never real content)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from session_kb.schema import (
    SCHEMA_VERSION,
    ChunkRecord,
    EmbeddingRecord,
    RawPtr,
    Source,
    TurnRecord,
    json_schemas,
)

SESSION = "synthetic-session"
EXCHANGE = f"{SESSION}:x1"

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "docs" / "schema"


def _turn(**overrides) -> TurnRecord:
    base = dict(
        session_id=SESSION,
        seq=1,
        exchange_id=EXCHANGE,
        actor="user",
        message="hello",
        source=Source(harness="claude-code", connector_version="0.0.0"),
        raw_ptr=RawPtr(uuids=["00000000-0000-0000-0000-000000000000"]),
        ts="2026-01-01T00:00:00Z",
    )
    base.update(overrides)
    return TurnRecord(**base)


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


def test_extra_field_is_rejected():
    # The contract forbids unknown keys: an extra field is a connector bug.
    with pytest.raises(ValidationError):
        _turn(unknown_field="oops")


def test_bad_actor_is_rejected():
    with pytest.raises(ValidationError):
        _turn(actor="robot")


def test_missing_required_field_is_rejected():
    with pytest.raises(ValidationError):
        Source(harness="claude-code")  # connector_version missing


def test_json_round_trip_is_lossless():
    rec = _turn(input_tokens=42, ext={"claude_code": {"is_sidechain": False}})
    restored = TurnRecord.model_validate_json(rec.model_dump_json())
    assert restored == rec


def test_committed_json_schema_is_in_sync():
    # Drift guard: the committed contract must match the models. Regenerate with
    # `python scripts/gen_schema.py` if this fails.
    for name, schema in json_schemas().items():
        path = SCHEMA_DIR / f"{name}.schema.json"
        assert path.exists(), f"missing committed schema: {path.name} — run scripts/gen_schema.py"
        committed = json.loads(path.read_text())
        assert committed == schema, f"{path.name} out of sync — run scripts/gen_schema.py"
