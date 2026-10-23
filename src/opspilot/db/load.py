"""Load the generated CSV files into PostgreSQL.

Usage:
    python -m opspilot.db.load --data-dir data/raw

The whole load runs in one transaction: drop and recreate tables, COPY every
CSV, build indexes and the ticket_features view, refresh planner statistics. PostgreSQL DDL is
transactional, so if any step fails the database is left exactly as it was.
"""

import argparse
from pathlib import Path

import pandas as pd
import psycopg
from psycopg import sql

from opspilot.db.connection import connect

# Assumes the package is run from the repository (editable install).
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "sql" / "schema"
FEATURES_FILE = SCHEMA_DIR.parent / "features" / "ticket_features.sql"

# Reference tables first, so foreign keys on tickets can be checked.
TABLES = ["teams", "sla_policies", "subcategories", "calendar_days", "tickets"]


def copy_csv(conn: psycopg.Connection, table: str, csv_path: Path) -> None:
    """Stream a CSV into a table with COPY, matching columns by header name."""
    with csv_path.open() as file:
        header = file.readline().strip().split(",")
        file.seek(0)
        statement = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true)").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(column) for column in header),
        )
        with conn.cursor().copy(statement) as copy:
            while chunk := file.read(1 << 20):
                copy.write(chunk)


def load_dataset(conn: psycopg.Connection, data_dir: Path) -> dict[str, int]:
    """Recreate the schema and load every table. Returns row counts per table.

    Commits only if every table loads and its row count matches the CSV.
    """
    missing = [table for table in TABLES if not (data_dir / f"{table}.csv").exists()]
    if missing:
        raise FileNotFoundError(f"missing CSV files in {data_dir}: {missing}. Run the generator first.")

    counts = {}
    with conn.transaction():
        conn.execute((SCHEMA_DIR / "001_create_tables.sql").read_text())
        for table in TABLES:
            csv_path = data_dir / f"{table}.csv"
            copy_csv(conn, table, csv_path)
            loaded = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
            expected = len(pd.read_csv(csv_path, usecols=[0]))
            if loaded != expected:
                raise RuntimeError(f"{table}: loaded {loaded} rows but {csv_path.name} has {expected}")
            counts[table] = loaded
        conn.execute((SCHEMA_DIR / "002_create_indexes.sql").read_text())
        conn.execute(FEATURES_FILE.read_text())
        conn.execute("ANALYZE")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the OpsPilot CSV files into PostgreSQL.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()

    with connect() as conn:
        counts = load_dataset(conn, args.data_dir)
    for table, rows in counts.items():
        print(f"{table:15} {rows:>7,} rows")


if __name__ == "__main__":
    main()
