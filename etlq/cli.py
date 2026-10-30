"""CLI: ``python -m etlq.cli generate DIR`` / ``run --db warehouse.db FILE...`` / ``query SQL``."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .generate import generate
from .load import connect
from .pipeline import run_file, summarize


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="etlq")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="create synthetic dirty sample data")
    g.add_argument("directory")
    r = sub.add_parser("run", help="run the pipeline on files")
    r.add_argument("--db", default="warehouse.db")
    r.add_argument("files", nargs="+")
    q = sub.add_parser("query", help="run a read-only SQL query")
    q.add_argument("--db", default="warehouse.db")
    q.add_argument("sql")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        if args.cmd == "generate":
            for path in generate(args.directory):
                print(path)
        elif args.cmd == "run":
            conn = connect(args.db)
            for f in args.files:
                report = run_file(conn, f)
                print(f"{f}: " + ("skipped (already processed)" if report is None else json.dumps(summarize(report))))
        else:
            if not args.sql.lstrip().lower().startswith(("select", "with")):
                print("error: only SELECT queries are allowed", file=sys.stderr)
                return 2
            conn = connect(args.db)
            for row in conn.execute(args.sql):
                print(dict(row))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
