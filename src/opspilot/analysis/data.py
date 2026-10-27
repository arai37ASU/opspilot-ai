"""Load database tables into pandas with types that suit analysis.

psycopg returns NUMERIC as Decimal and nullable integers or booleans as Python
objects. Left alone, those become `object` columns in pandas, which breaks
arithmetic and plotting in quiet ways. read_sql converts them using the
column types PostgreSQL reports.
"""

import pandas as pd
import psycopg

from opspilot.db.connection import connect

# PostgreSQL type OIDs, from the pg_type catalogue.
NUMERIC = 1700
INTEGERS = {20, 21, 23}  # bigint, smallint, integer
BOOLEAN = 16


def read_sql(conn: psycopg.Connection, query: str, params: list | dict | None = None) -> pd.DataFrame:
    cursor = conn.execute(query, params)
    columns = [column.name for column in cursor.description]
    frame = pd.DataFrame(cursor.fetchall(), columns=columns)

    for column in cursor.description:
        if column.type_code == NUMERIC:
            frame[column.name] = frame[column.name].astype("float64")
        elif column.type_code in INTEGERS:
            frame[column.name] = frame[column.name].astype("Int64")
        elif column.type_code == BOOLEAN:
            frame[column.name] = frame[column.name].astype("boolean")
    return frame


def load_tickets(conn: psycopg.Connection | None = None) -> pd.DataFrame:
    """All tickets, including outcome columns. For analysis, not for model features."""
    return _load("SELECT * FROM tickets ORDER BY created_at, ticket_id", conn)


def load_features(conn: psycopg.Connection | None = None) -> pd.DataFrame:
    """The ticket_features view: creation-time features plus the sla_breached label."""
    return _load("SELECT * FROM ticket_features ORDER BY created_at, ticket_id", conn)


def _load(query: str, conn: psycopg.Connection | None) -> pd.DataFrame:
    if conn is not None:
        return read_sql(conn, query)
    with connect() as new_conn:
        return read_sql(new_conn, query)
