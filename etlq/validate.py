"""Data-quality checks. Bad rows are quarantined with a reason instead of silently dropped."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALLOWED_CURRENCIES = frozenset({"USD", "EUR", "GBP", "INR", "MXN", "PHP", "SGD", "AUD"})
ALLOWED_STATUS = frozenset({"pending", "settled", "failed"})
REQUIRED = ("id", "amount", "currency", "ts", "status")


@dataclass
class QualityReport:
    total: int = 0
    valid: int = 0
    rejected: int = 0
    duplicates_removed: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        return round(self.valid / self.total, 4) if self.total else 0.0

    def add_reason(self, reason: str) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


def check_record(r: dict[str, Any]) -> str | None:
    """Return the first failed rule name, or None when the record is valid."""
    for name in REQUIRED:
        if r.get(name) in (None, ""):
            return f"missing_{name}"
    if r["amount"] <= 0:
        return "non_positive_amount"
    if r["currency"] not in ALLOWED_CURRENCIES:
        return "unknown_currency"
    if r["status"] not in ALLOWED_STATUS:
        return "invalid_status"
    return None


def validate(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]], QualityReport]:
    report = QualityReport(total=len(records))
    good: list[dict[str, Any]] = []
    bad: list[tuple[dict[str, Any], str]] = []
    for r in records:
        reason = check_record(r)
        if reason:
            bad.append((r, reason))
            report.rejected += 1
            report.add_reason(reason)
        else:
            good.append(r)
            report.valid += 1
    return good, bad, report
