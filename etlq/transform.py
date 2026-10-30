"""Cleaning and normalisation. Pure functions, no I/O."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

FIELD_ALIASES = {
    "txn_id": "id", "transaction_id": "id", "id": "id",
    "amount": "amount", "amt": "amount",
    "currency": "currency", "ccy": "currency",
    "timestamp": "ts", "ts": "ts", "created_at": "ts",
    "status": "status", "customer_id": "customer_id", "customerid": "customer_id",
}


def parse_ts(value: Any) -> str | None:
    """Parse ISO-8601 (with Z/offset) or epoch seconds into a UTC ISO string; None if invalid."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        if text.replace(".", "", 1).isdigit():
            dt = datetime.fromtimestamp(float(text), tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return None


def parse_amount(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def normalise(record: dict[str, Any]) -> dict[str, Any]:
    """Map aliases, trim strings, upper-case currency, parse timestamp and amount."""
    out: dict[str, Any] = {}
    for key, value in record.items():
        canon = FIELD_ALIASES.get(key.strip().lower())
        if canon:
            out[canon] = value.strip() if isinstance(value, str) else value
    out["currency"] = (out.get("currency") or "").upper() or None
    out["status"] = (out.get("status") or "").lower() or None
    out["ts"] = parse_ts(out.get("ts"))
    out["amount"] = parse_amount(out.get("amount"))
    if out.get("id") in ("", None):
        out["id"] = None
    return out


def dedupe_latest(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep the record with the latest timestamp per id. Returns (records, duplicates_removed)."""
    best: dict[str, dict[str, Any]] = {}
    no_id: list[dict[str, Any]] = []
    for r in records:
        rid = r.get("id")
        if rid is None:
            no_id.append(r)
        elif rid not in best or (r.get("ts") or "") >= (best[rid].get("ts") or ""):
            best[rid] = r
    removed = len(records) - len(best) - len(no_id)
    return list(best.values()) + no_id, removed
