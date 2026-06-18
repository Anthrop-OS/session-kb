"""Idempotent batch ingest: connector → scrub → chunk → embed → L1 records.

Decoupled from session lifecycle (cron / manual). Idempotency comes from L0
existence checks — no separate state database. A mandatory secret scrub runs
before any write to the L1 git repo.
"""

from __future__ import annotations

import argparse


def run(argv: list[str] | None = None) -> int:
    raise NotImplementedError("milestone: idempotent batch ingest")


def main() -> int:
    parser = argparse.ArgumentParser(prog="session-ingest")
    parser.add_argument("paths", nargs="*", help="session transcript paths")
    parser.parse_args()
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
