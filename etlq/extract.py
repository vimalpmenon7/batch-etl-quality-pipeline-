"""Extract structured (CSV) and semi-structured (JSON lines, nested) payment records."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterator


def _flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts: {"a": {"b": 1}} -> {"a_b": 1}."""
    out: dict[str, Any] = {}
    for key, value in obj.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{name}_"))
        else:
            out[name] = value
    return out


def read_csv(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as fh:
        yield from csv.DictReader(fh)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield flattened records; malformed lines are yielded as ``{"_corrupt": line}``."""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                yield _flatten(record) if isinstance(record, dict) else {"_corrupt": line}
            except json.JSONDecodeError:
                yield {"_corrupt": line}


def extract(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if p.suffix == ".csv":
        return list(read_csv(p))
    if p.suffix in {".jsonl", ".ndjson"}:
        return list(read_jsonl(p))
    raise ValueError(f"Unsupported file type: {p.suffix}")
