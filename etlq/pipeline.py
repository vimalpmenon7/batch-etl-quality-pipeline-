"""Orchestration: extract -> normalise -> validate -> dedupe -> load, with run logging."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .extract import extract
from .load import already_processed, upsert_transactions, write_quarantine
from .transform import dedupe_latest, normalise
from .validate import QualityReport, validate

log = logging.getLogger("etlq")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_file(conn: sqlite3.Connection, path: str | Path) -> QualityReport | None:
    """Process one file. Returns None if this exact file content was already loaded."""
    p = Path(path)
    digest = file_sha256(p)
    if already_processed(conn, digest):
        log.info("skip %s (already processed)", p.name)
        return None

    run_id = uuid.uuid4().hex[:12]
    raw = extract(p)
    corrupt = [r for r in raw if "_corrupt" in r]
    parsed = [normalise(r) for r in raw if "_corrupt" not in r]
    # Validate BEFORE deduplicating so an invalid duplicate can never displace a valid record.
    valid_rows, bad, report = validate(parsed)
    good, removed = dedupe_latest(valid_rows)
    report.valid = len(good)

    # Unparseable lines count as rejected rows too, so totals reconcile with the source file.
    for c in corrupt:
        bad.append((c, "corrupt_record"))
        report.add_reason("corrupt_record")
    report.rejected += len(corrupt)
    report.total += len(corrupt)
    report.duplicates_removed = removed

    with conn:  # one transaction: all-or-nothing
        upsert_transactions(conn, good, p.name)
        write_quarantine(conn, run_id, bad)
        conn.execute(
            "INSERT INTO pipeline_runs VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, p.name, digest, datetime.now(timezone.utc).isoformat(timespec="seconds"),
             report.total, report.valid, report.rejected, removed, report.pass_rate),
        )
    log.info("run %s: %d valid, %d rejected, %d duplicates", run_id, report.valid, report.rejected, removed)
    return report


def summarize(report: QualityReport) -> dict[str, Any]:
    return {
        "total": report.total, "valid": report.valid, "rejected": report.rejected,
        "duplicates_removed": report.duplicates_removed, "pass_rate": report.pass_rate,
        "reasons": dict(sorted(report.reasons.items())),
    }
