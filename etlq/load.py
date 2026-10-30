"""SQLite warehouse: idempotent upserts, quarantine table, run log and SQL models."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS fact_transactions (
    id TEXT PRIMARY KEY, amount REAL NOT NULL, currency TEXT NOT NULL,
    ts TEXT NOT NULL, status TEXT NOT NULL, customer_id TEXT, source_file TEXT
);
CREATE TABLE IF NOT EXISTS quarantine (
    run_id TEXT, reason TEXT, payload TEXT
);
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY, source_file TEXT, file_hash TEXT, started_at TEXT,
    total INTEGER, valid INTEGER, rejected INTEGER, duplicates_removed INTEGER, pass_rate REAL
);
CREATE INDEX IF NOT EXISTS idx_fact_ts ON fact_transactions(ts);
DROP VIEW IF EXISTS daily_volume;
CREATE VIEW daily_volume AS
SELECT substr(ts, 1, 10) AS day, currency,
       COUNT(*) AS txn_count, ROUND(SUM(amount), 2) AS total_amount
FROM fact_transactions
WHERE status = 'settled'
GROUP BY day, currency;
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def already_processed(conn: sqlite3.Connection, file_hash: str) -> bool:
    row = conn.execute("SELECT 1 FROM pipeline_runs WHERE file_hash = ?", (file_hash,)).fetchone()
    return row is not None


def upsert_transactions(conn: sqlite3.Connection, rows: list[dict[str, Any]], source: str) -> None:
    """Insert or update by primary key, so re-running a load never creates duplicates."""
    conn.executemany(
        """INSERT INTO fact_transactions (id, amount, currency, ts, status, customer_id, source_file)
           VALUES (:id, :amount, :currency, :ts, :status, :customer_id, :source)
           ON CONFLICT(id) DO UPDATE SET amount=excluded.amount, currency=excluded.currency,
             ts=excluded.ts, status=excluded.status, customer_id=excluded.customer_id,
             source_file=excluded.source_file
           WHERE excluded.ts >= fact_transactions.ts""",
        [{**{"customer_id": None}, **r, "source": source} for r in rows],
    )


def write_quarantine(conn: sqlite3.Connection, run_id: str, bad: list[tuple[dict[str, Any], str]]) -> None:
    conn.executemany(
        "INSERT INTO quarantine (run_id, reason, payload) VALUES (?, ?, ?)",
        [(run_id, reason, json.dumps(rec, default=str)) for rec, reason in bad],
    )
