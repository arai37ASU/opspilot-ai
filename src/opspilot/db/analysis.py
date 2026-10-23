"""Run the business analysis queries in sql/analysis and save each result.

Usage:
    python -m opspilot.db.analysis --output-dir reports/sql

Each named query in each file becomes one CSV, named <file>__<query>.csv,
so every number quoted in the findings write-up can be traced to a file.
"""

import argparse
from pathlib import Path

import pandas as pd
import psycopg

from opspilot.db.connection import connect
from opspilot.db.sql_files import NamedQuery, parse_named_queries

ANALYSIS_DIR = Path(__file__).resolve().parents[3] / "sql" / "analysis"


def analysis_queries(directory: Path = ANALYSIS_DIR) -> dict[str, list[NamedQuery]]:
    """Queries per analysis file, keyed by file stem, in file-name order."""
    return {path.stem: parse_named_queries(path.read_text()) for path in sorted(directory.glob("*.sql"))}


def run_query(conn: psycopg.Connection, query: NamedQuery) -> pd.DataFrame:
    cursor = conn.execute(query.sql)
    columns = [column.name for column in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def run_analysis(conn: psycopg.Connection, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for file_stem, queries in analysis_queries().items():
        for query in queries:
            path = output_dir / f"{file_stem}__{query.name}.csv"
            run_query(conn, query).to_csv(path, index=False)
            written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the OpsPilot SQL analysis and save results as CSV.")
    parser.add_argument("--output-dir", type=Path, default=Path("reports/sql"))
    args = parser.parse_args()

    with connect() as conn:
        written = run_analysis(conn, args.output_dir)
    for path in written:
        rows = sum(1 for _ in path.open()) - 1
        print(f"{rows:>5} rows  {path}")


if __name__ == "__main__":
    main()
