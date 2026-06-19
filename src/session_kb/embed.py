"""Embedding via local ONNX all-MiniLM (llm-embed-onnx).

Vectors are exported as jsonl EmbeddingRecords committed to the L1 data repo, so
an index rebuild needs no inference. The model runs only here (ingest) and when
embedding a query string at search time.
"""

from __future__ import annotations

import hashlib

from .schema import EmbeddingRecord

MODEL = "minilm-v2"
DIM = 384


def embed(text: str) -> list[float]:
    raise NotImplementedError("milestone: embedding (llm-embed-onnx wrapper)")


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_chunk(exchange_id: str, text: str) -> EmbeddingRecord:
    return EmbeddingRecord(
        exchange_id=exchange_id,
        model=MODEL,
        dim=DIM,
        embedding=embed(text),
        content_hash=content_hash(text),
    )
