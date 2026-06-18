"""L2 index build: sqlite FTS5 (BM25 over scrubbed verbatim) + sqlite-vec (KNN).

The index is derived and disposable: ``L2 = f(L1)``. It is rebuildable on any
node purely from L1 jsonl (records + committed embeddings), with no inference.
"""

from __future__ import annotations

from pathlib import Path


def rebuild(l1_dir: Path, db_path: Path) -> None:
    raise NotImplementedError("milestone: sqlite rebuild (FTS5 + vec)")
