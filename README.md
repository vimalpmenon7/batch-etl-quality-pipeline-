# batch-etl-quality-pipeline

![CI](https://github.com/vimalpmenon7/batch-etl-quality-pipeline/actions/workflows/ci.yml/badge.svg)

A small **batch ETL pipeline** in Python and SQL that ingests structured (CSV) and semi-structured (nested JSON lines) payment records, cleans and validates them, quarantines bad rows with a reason, and loads good rows into a SQLite warehouse with **idempotent upserts**. Standard library only.

## Problem

Data from multiple sources arrives with different field names, formats and mistakes. If a pipeline silently drops bad rows, or loads the same file twice, downstream reports are wrong and nobody can tell why.

## Solution

```
CSV / JSONL --> extract (flatten nested JSON, flag corrupt lines)
            --> normalise (alias mapping, trim, UTC timestamps, amounts)
            --> validate (quality rules)  --reject--> quarantine table (with reason)
            --> deduplicate (latest timestamp wins, valid rows only)
            --> upsert into fact_transactions  --> SQL view daily_volume
            --> pipeline_runs log (counts, pass rate, file hash)
```

## Features

- **Structured and semi-structured input:** CSV and JSON lines; nested objects are flattened; malformed lines are quarantined instead of crashing the run.
- **Normalisation:** field aliases (`txn_id`/`transaction_id`/`id`), upper-case currency, ISO-8601 with offsets and epoch seconds converted to UTC, amounts like `1,250.50` parsed.
- **Data-quality checks:** required fields, positive amount, allowed currency and status. Every rejection keeps its payload and a reason in the `quarantine` table.
- **Validate before deduplicating,** so an invalid duplicate can never overwrite a valid record (found and fixed while testing this project).
- **Idempotent loads:** re-running the same file is skipped by SHA-256 hash; upserts use `ON CONFLICT ... DO UPDATE` and ignore older versions of a record.
- **Atomic runs:** each file loads in one transaction.
- **Run log and reconciliation:** `total = valid + rejected + duplicates_removed` is asserted in tests.
- **SQL model:** `daily_volume` view aggregates settled transactions by day and currency.

## Tech stack

Python 3.10+ (standard library), SQLite, SQL, GitHub Actions, unittest.

## Project structure

```
etlq/
  extract.py     CSV / JSONL readers, JSON flattening
  transform.py   normalisation, timestamp/amount parsing, deduplication
  validate.py    quality rules and QualityReport
  load.py        schema, upserts, quarantine writer, SQL view
  pipeline.py    orchestration and run logging
  generate.py    synthetic dirty sample data
  cli.py         command line
tests/           14 unit tests
```

## Usage

```bash
git clone https://github.com/vimalpmenon7/batch-etl-quality-pipeline.git
cd batch-etl-quality-pipeline
python -m etlq.cli generate sample_data           # synthetic data with injected errors
python -m etlq.cli run --db warehouse.db sample_data/payments.csv sample_data/payments.jsonl
python -m etlq.cli run --db warehouse.db sample_data/payments.csv   # skipped: already processed
python -m etlq.cli query --db warehouse.db "SELECT * FROM daily_volume ORDER BY total_amount DESC LIMIT 3"
```

Real output from the bundled synthetic data:

```
payments.csv:   {"total": 506, "valid": 501, "rejected": 4, "duplicates_removed": 1, "pass_rate": 0.9901,
                 "reasons": {"missing_id": 1, "missing_ts": 1, "non_positive_amount": 1, "unknown_currency": 1}}
payments.jsonl: {"total": 101, "valid": 100, "rejected": 1, "duplicates_removed": 0, "pass_rate": 0.9901,
                 "reasons": {"corrupt_record": 1}}
payments.csv:   skipped (already processed)
```

## Testing

```bash
python -m unittest discover -s tests -t .      # 14 tests
```

Covers timestamp and amount parsing, aliasing, deduplication, each quality rule, corrupt-line handling, idempotent re-runs, upsert ordering, count reconciliation and the SQL view.

## Limitations

- All data is **synthetic**. Real payment data would need schema evolution, larger-than-memory processing and PII handling.
- Single-process SQLite; no Apache Spark, PySpark or Airflow. The stages are plain functions, so they could be wrapped as Airflow tasks or rewritten in PySpark.
- Batch only; no streaming or near-real-time ingestion.
- No cloud deployment (for example S3 as the source) in this repo.
- The `query` command only checks that the SQL starts with SELECT or WITH; it is a convenience, not a security boundary.

## Future improvements

- Airflow DAG with one task per stage, and a PySpark version for large inputs.
- Read from and write to Amazon S3; Parquet output.
- Row-level data-quality metrics over time and alerting on pass-rate drops.

## License

MIT
