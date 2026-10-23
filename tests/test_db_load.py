"""Integration tests for the schema and loader, run against opspilot_test."""

import shutil

import pandas as pd
import psycopg
import pytest
from psycopg import sql

from opspilot.db.load import TABLES, load_dataset

pytestmark = pytest.mark.db


def table_count(db_conn, table):
    return db_conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]


def test_every_table_matches_its_csv(db_conn, data_dir):
    for table in TABLES:
        assert table_count(db_conn, table) == len(pd.read_csv(data_dir / f"{table}.csv"))


def test_reloading_replaces_data_instead_of_appending(db_conn, data_dir):
    before = table_count(db_conn, "tickets")
    load_dataset(db_conn, data_dir)
    assert table_count(db_conn, "tickets") == before


def test_failed_load_leaves_previous_data_in_place(db_conn, data_dir, tmp_path):
    broken_dir = tmp_path / "broken"
    shutil.copytree(data_dir, broken_dir)
    # Read as plain text so every other value round-trips unchanged; only the
    # planted error should make the load fail.
    tickets = pd.read_csv(broken_dir / "tickets.csv", dtype=str, keep_default_na=False)
    tickets.loc[len(tickets) - 1, "priority"] = "P9"
    tickets.to_csv(broken_dir / "tickets.csv", index=False)

    before = table_count(db_conn, "tickets")
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as error:
        load_dataset(db_conn, broken_dir)
    assert error.value.diag.constraint_name == "tickets_ticket_type_priority_fkey"
    assert table_count(db_conn, "tickets") == before


def test_missing_csv_is_reported(db_conn, tmp_path):
    with pytest.raises(FileNotFoundError):
        load_dataset(db_conn, tmp_path)


def test_breach_rate_matches_the_csv(db_conn, data_dir):
    tickets = pd.read_csv(data_dir / "tickets.csv")
    expected = tickets["sla_breached"].dropna().astype(bool).mean()
    loaded = db_conn.execute("SELECT avg(sla_breached::int) FROM tickets").fetchone()[0]
    assert float(loaded) == pytest.approx(expected)


def test_indexes_exist(db_conn):
    names = {row[0] for row in db_conn.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'tickets'")}
    assert {"tickets_created_at_idx", "tickets_team_created_at_idx", "tickets_subcategory_created_at_idx"} <= names


# --- Constraints reject invalid tickets ----------------------------------------


@pytest.fixture
def valid_ticket(db_conn):
    """A resolved P3 service request, used as the starting point for invalid variants."""
    cursor = db_conn.execute(
        "SELECT * FROM tickets WHERE status = 'resolved' AND ticket_type = 'service_request' "
        "AND priority = 'P3' AND satisfaction_score IS NOT NULL LIMIT 1"
    )
    columns = [column.name for column in cursor.description]
    return dict(zip(columns, cursor.fetchone()))


def insert_ticket(db_conn, row):
    statement = sql.SQL("INSERT INTO tickets ({}) VALUES ({})").format(
        sql.SQL(", ").join(sql.Identifier(column) for column in row),
        sql.SQL(", ").join(sql.Placeholder() for _ in row),
    )
    db_conn.execute(statement, list(row.values()))


def test_a_valid_ticket_is_accepted(db_conn, valid_ticket):
    with db_conn.transaction(force_rollback=True):
        insert_ticket(db_conn, {**valid_ticket, "ticket_id": "TKT-TEST"})


@pytest.mark.parametrize(
    "change, constraint",
    [
        ({"priority": "P1"}, "tickets_ticket_type_priority_fkey"),
        ({"category": "Network"}, "tickets_subcategory_category_ticket_type_fkey"),
        ({"assigned_team": "Facilities"}, "tickets_assigned_team_fkey"),
        ({"channel": "fax"}, "tickets_channel_check"),
        ({"satisfaction_score": 6}, "tickets_satisfaction_score_check"),
        ({"status": "open"}, "outcomes_only_when_resolved"),
        ({"resolved_at": pd.Timestamp("2023-01-01")}, "resolved_after_created"),
        ({"sla_breached": None}, "outcomes_only_when_resolved"),
        ("flip_breach", "breach_matches_definition"),
        ("duplicate_id", "tickets_pkey"),
    ],
)
def test_constraints_reject_invalid_tickets(db_conn, valid_ticket, change, constraint):
    row = {**valid_ticket, "ticket_id": "TKT-TEST"}
    if change == "flip_breach":
        row["sla_breached"] = not row["sla_breached"]
    elif change == "duplicate_id":
        row["ticket_id"] = valid_ticket["ticket_id"]
    else:
        row.update(change)

    with pytest.raises(psycopg.errors.IntegrityError) as error:
        with db_conn.transaction():
            insert_ticket(db_conn, row)
    assert error.value.diag.constraint_name == constraint
