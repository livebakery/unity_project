"""Persistence for cross-run state (last seen file mtime, fair values, alert levels)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_PATH = Path("state.json")


def load(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    if not path.exists():
        return {
            "last_modified_time": None,
            "last_fair_values": {},
            "last_alert_levels": {},
        }
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("last_modified_time", None)
    data.setdefault("last_fair_values", {})
    data.setdefault("last_alert_levels", {})
    return data


def save(state: dict[str, Any], path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name, suffix=".tmp", dir=str(path.parent) or "."
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
