"""Generate SYNTHETIC payment data with deliberately dirty rows (for demos and tests)."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path


def generate(directory: str | Path, n: int = 500, seed: int = 11) -> tuple[Path, Path]:
    rng = random.Random(seed)
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    ccys = ["USD", "EUR", "GBP", "INR", "MXN", "PHP"]
    statuses = ["pending", "settled", "failed"]

    csv_rows = []
    for i in range(n):
        csv_rows.append({
            "txn_id": f"T{i:05d}", "amount": f"{rng.uniform(5, 5000):.2f}",
            "currency": rng.choice(ccys), "timestamp": f"2026-10-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:00:00Z",
            "status": rng.choice(statuses), "customer_id": f"C{rng.randint(1, 80):03d}",
        })
    # inject dirty rows
    csv_rows.append({**csv_rows[0], "amount": "-10"})                 # same id as a valid row but invalid amount
    csv_rows.append({**csv_rows[1], "txn_id": "T90001", "currency": "ZZZ"})  # unknown currency
    csv_rows.append({**csv_rows[2], "txn_id": "T90002", "timestamp": "not-a-date"})
    csv_rows.append({**csv_rows[3], "txn_id": "", })                  # missing id
    csv_rows.append(dict(csv_rows[5]))                                # exact duplicate of a valid row
    csv_rows.append({**csv_rows[4], "txn_id": "T90003", "currency": " usd ", "amount": "1,250.50"})  # fixable
    csv_path = d / "payments.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(csv_rows[0].keys()))
        w.writeheader()
        w.writerows(csv_rows)

    jsonl_path = d / "payments.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for i in range(n // 5):
            fh.write(json.dumps({
                "transaction_id": f"J{i:05d}", "amt": round(rng.uniform(5, 5000), 2),
                "ccy": rng.choice(ccys), "created_at": 1_790_000_000 + rng.randint(0, 2_000_000),
                "status": rng.choice(statuses), "customer": {"id": f"C{rng.randint(1, 80):03d}"},
            }) + "\n")
        fh.write("{this is not json\n")
    return csv_path, jsonl_path
