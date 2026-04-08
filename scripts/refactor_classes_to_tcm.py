#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGER_ROOT = REPO_ROOT / "manager"


def rewrite_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text

    # 1) module imports
    text = text.replace("from classes.", "from tcm.")
    text = text.replace("import classes.", "import tcm.")

    # 2) strings in tests (patch, etc.)
    text = text.replace('"classes.', '"tcm.')
    text = text.replace("'classes.", "'tcm.")

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> int:
    if not MANAGER_ROOT.exists():
        raise SystemExit(f"manager/ not found under {REPO_ROOT}")

    classes_dir = MANAGER_ROOT / "classes"
    tcm_dir = MANAGER_ROOT / "tcm"

    if not classes_dir.exists():
        raise SystemExit(
            f"manager/classes does not exist (already renamed?): {classes_dir}"
        )

    if tcm_dir.exists():
        raise SystemExit(
            f"manager/tcm already exists, aborting to avoid overwriting: {tcm_dir}"
        )

    # 1) Rename physical folder: classes -> tcm
    classes_dir.rename(tcm_dir)

    # 2) Rewrite imports in all .py files under manager/
    changed = 0
    for root, _, files in os.walk(MANAGER_ROOT):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = Path(root) / name
            if rewrite_file(path):
                changed += 1

    print("[refactor] Renamed manager/classes -> manager/tcm")
    print(f"[refactor] Python files updated: {changed}")
    print("[refactor] Now run ruff/black/pytest to validate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
