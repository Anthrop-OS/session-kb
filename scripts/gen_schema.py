#!/usr/bin/env python3
"""Export the canonical record models to JSON Schema under docs/schema/.

The Pydantic models in ``session_kb.schema`` are the source of truth; the
committed JSON Schema files are the language-neutral contract a non-Python
connector validates against. Run this whenever the models change; CI's
drift-guard test fails if the committed files fall out of sync.

    python scripts/gen_schema.py
"""

from __future__ import annotations

import json
from pathlib import Path

from session_kb.schema import json_schemas

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "schema"


def write() -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, schema in json_schemas().items():
        path = OUT_DIR / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        written.append(path)
    return written


if __name__ == "__main__":
    for p in write():
        print(f"wrote {p}")
