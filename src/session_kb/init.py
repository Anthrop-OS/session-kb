"""Scaffold a fresh private L1 data repo from the bundled template.

The tool repo owns the canonical schema and layer model, so it also owns the
data-repo skeleton. ``session-kb-init <dir>`` materializes that skeleton so a new
node/agent gets a consistent L1 data repo without hand-copying files.
"""

from __future__ import annotations

import argparse
import shutil
from importlib import resources
from pathlib import Path

_TEMPLATE = ("session_kb", "templates", "data_repo")


def init_data_repo(target: Path) -> list[Path]:
    """Copy the data-repo template into ``target``; return files written."""
    written: list[Path] = []
    tpl_root = resources.files(_TEMPLATE[0]).joinpath(*_TEMPLATE[1:])
    with resources.as_file(tpl_root) as tpl_dir:
        tpl_dir = Path(tpl_dir)
        for src in sorted(tpl_dir.rglob("*")):
            rel = src.relative_to(tpl_dir)
            dest = target / rel
            if src.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            # `gitignore` ships dotless (wheels drop leading-dot files); restore it.
            if dest.name == "gitignore":
                dest = dest.with_name(".gitignore")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            written.append(dest)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="session-kb-init",
        description="Scaffold a private L1 data repo from the bundled template.",
    )
    parser.add_argument("target", type=Path, help="directory to scaffold")
    args = parser.parse_args()
    written = init_data_repo(args.target)
    print(f"scaffolded L1 data repo at {args.target} ({len(written)} files)")
    print("next: cd in, `git init`, create a PRIVATE remote, commit, push.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
