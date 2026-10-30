import tempfile
import unittest
from pathlib import Path

from etlq.extract import extract, read_jsonl
from etlq.generate import generate
from etlq.load import connect
from etlq.pipeline import run_file
from etlq.transform import dedupe_latest, normalise, parse_amount, parse_ts
from etlq.validate import check_record


class TransformTests(unittest.TestCase):
    def test_parse_ts_variants(self):
        self.assertEqual(parse_ts("2026-10-01T05:30:00+05:30"), "2026-10-01T00:00:00Z")
        self.assertEqual(parse_ts("2026-10-01T00:00:00Z"), "2026-10-01T00:00:00Z")
        self.assertEqual(parse_ts("2026-10-01"), "2026-10-01T00:00:00Z")
        self.assertEqual(parse_ts("0"), "1970-01-01T00:00:00Z")
        self.assertIsNone(parse_ts("not-a-date"))
        self.assertIsNone(parse_ts(""))

    def test_parse_amount(self):
        self.assertEqual(parse_amount("1,250.504"), 1250.5)
        self.assertIsNone(parse_amount("abc"))
        self.assertIsNone(parse_amount(None))

    def test_normalise_maps_aliases_and_cleans(self):
        r = normalise({"txn_id": " T1 ", "amt": "10", "ccy": " usd ", "created_at": "2026-10-01T00:00:00Z", "status": "SETTLED"})
        self.assertEqual((r["id"], r["amount"], r["currency"], r["status"]), ("T1", 10.0, "USD", "settled"))

    def test_dedupe_keeps_latest_timestamp(self):
        rows = [{"id": "a", "ts": "2026-10-01T00:00:00Z", "v": 1}, {"id": "a", "ts": "2026-10-02T00:00:00Z", "v": 2}]
        out, removed = dedupe_latest(rows)
        self.assertEqual((len(out), removed, out[0]["v"]), (1, 1, 2))


class ValidateTests(unittest.TestCase):
    base = {"id": "1", "amount": 5.0, "currency": "USD", "ts": "2026-10-01T00:00:00Z", "status": "settled"}

    def test_valid_and_each_failure(self):
        self.assertIsNone(check_record(self.base))
        self.assertEqual(check_record({**self.base, "amount": -1}), "non_positive_amount")
        self.assertEqual(check_record({**self.base, "currency": "ZZZ"}), "unknown_currency")
        self.assertEqual(check_record({**self.base, "status": "weird"}), "invalid_status")
        self.assertEqual(check_record({**self.base, "id": None}), "missing_id")
        self.assertEqual(check_record({**self.base, "ts": None}), "missing_ts")


class ExtractTests(unittest.TestCase):
    def test_jsonl_flattens_and_flags_corrupt_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.jsonl"
            p.write_text('{"a": {"b": 1}}\n{bad\n\n', encoding="utf-8")
            rows = list(read_jsonl(p))
            self.assertEqual(rows[0], {"a_b": 1})
            self.assertIn("_corrupt", rows[1])

    def test_unsupported_extension(self):
        with self.assertRaises(ValueError):
            extract("data.parquet")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv, self.jsonl = generate(self.tmp.name, n=200)
        self.conn = connect()

    def tearDown(self):
        self.tmp.cleanup()

    def test_csv_run_quarantines_bad_rows_and_reconciles_counts(self):
        rep = run_file(self.conn, self.csv)
        self.assertEqual(rep.total, rep.valid + rep.rejected + rep.duplicates_removed)
        self.assertGreaterEqual(rep.reasons.get("unknown_currency", 0), 1)
        self.assertGreaterEqual(rep.reasons.get("missing_id", 0), 1)
        self.assertGreaterEqual(rep.reasons.get("missing_ts", 0), 1)
        self.assertEqual(rep.duplicates_removed, 1)
        loaded = self.conn.execute("SELECT COUNT(*) FROM fact_transactions").fetchone()[0]
        self.assertEqual(loaded, rep.valid)
        q = self.conn.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0]
        self.assertEqual(q, rep.rejected)

    def test_invalid_duplicate_does_not_displace_valid_record(self):
        run_file(self.conn, self.csv)
        row = self.conn.execute("SELECT amount FROM fact_transactions WHERE id='T00000'").fetchone()
        self.assertIsNotNone(row)
        self.assertGreater(row["amount"], 0)

    def test_fixable_row_is_cleaned_not_rejected(self):
        run_file(self.conn, self.csv)
        row = self.conn.execute("SELECT amount, currency FROM fact_transactions WHERE id='T90003'").fetchone()
        self.assertEqual((row["amount"], row["currency"]), (1250.5, "USD"))

    def test_rerun_same_file_is_skipped(self):
        run_file(self.conn, self.csv)
        before = self.conn.execute("SELECT COUNT(*) FROM fact_transactions").fetchone()[0]
        self.assertIsNone(run_file(self.conn, self.csv))
        after = self.conn.execute("SELECT COUNT(*) FROM fact_transactions").fetchone()[0]
        self.assertEqual(before, after)

    def test_semi_structured_jsonl_loads_with_corrupt_line_rejected(self):
        rep = run_file(self.conn, self.jsonl)
        self.assertEqual(rep.reasons.get("corrupt_record"), 1)
        self.assertEqual(rep.valid, 40)
        cust = self.conn.execute("SELECT COUNT(*) FROM fact_transactions WHERE customer_id IS NOT NULL").fetchone()[0]
        self.assertEqual(cust, 40)

    def test_upsert_is_idempotent_and_latest_wins(self):
        from etlq.load import upsert_transactions
        row = {"id": "X", "amount": 1.0, "currency": "USD", "ts": "2026-10-02T00:00:00Z", "status": "settled"}
        upsert_transactions(self.conn, [row], "a")
        upsert_transactions(self.conn, [{**row, "amount": 9.0, "ts": "2026-10-01T00:00:00Z"}], "b")  # older: ignored
        upsert_transactions(self.conn, [{**row, "amount": 7.0}], "c")  # same ts: applied
        r = self.conn.execute("SELECT COUNT(*) c, MAX(amount) a FROM fact_transactions WHERE id='X'").fetchone()
        self.assertEqual((r["c"], r["a"]), (1, 7.0))

    def test_daily_volume_view_counts_only_settled(self):
        run_file(self.conn, self.csv)
        total_view = self.conn.execute("SELECT SUM(txn_count) FROM daily_volume").fetchone()[0]
        settled = self.conn.execute("SELECT COUNT(*) FROM fact_transactions WHERE status='settled'").fetchone()[0]
        self.assertEqual(total_view, settled)


if __name__ == "__main__":
    unittest.main()
