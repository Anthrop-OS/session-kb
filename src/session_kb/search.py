"""session-search CLI: semantic + keyword retrieval with RRF fusion.

embed(query) → sqlite-vec KNN over chunk vectors, in parallel with FTS5 BM25
over scrubbed-verbatim records → reciprocal-rank fusion → return summaries plus
a raw_ptr into the encrypted L0 layer for full-fidelity recovery.
"""

from __future__ import annotations

import argparse


def search(query: str, k: int = 10) -> list[dict]:
    raise NotImplementedError("milestone: session-search CLI (RRF)")


def main() -> int:
    parser = argparse.ArgumentParser(prog="session-search")
    parser.add_argument("query", help="natural-language query")
    parser.add_argument("-k", type=int, default=10, help="results to return")
    args = parser.parse_args()
    for hit in search(args.query, k=args.k):
        print(hit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
