"""Embedding via local ONNX all-MiniLM (llm-embed-onnx).

Vectors are exported as jsonl EmbeddingRecords committed to the L1 data repo, so
an index rebuild needs no inference. The model runs only here (ingest) and when
embedding a query string at search time.
"""

from __future__ import annotations

from .schema import EmbeddingRecord

MODEL = "minilm-v2"
DIM = 384


def embed(text: str) -> list[float]:
    raise NotImplementedError("milestone: embedding (llm-embed-onnx wrapper)")


def embed_chunk(chunk_id: str, text: str) -> EmbeddingRecord:
    return EmbeddingRecord(chunk_id=chunk_id, model=MODEL, dim=DIM, vec=embed(text))
