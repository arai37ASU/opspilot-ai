"""Model features for a single ticket at the moment it is created.

Training used the ticket_features view, computed for every stored ticket.
Serving needs the same values for a ticket that may not be stored yet, so the
database-derived features come from sql/features/new_ticket_features.sql,
which mirrors the view expression by expression. The parity test in
tests/test_online_features.py checks that the two agree exactly.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg

from opspilot.analysis.data import read_sql
from opspilot.modeling import config
from opspilot.modeling.dataset import feature_matrix

QUERY = (Path(__file__).resolve().parents[3] / "sql" / "features" / "new_ticket_features.sql").read_text()


class InvalidTicket(ValueError):
    """The ticket cannot be scored, for example an unknown team or a P1 service request."""


@dataclass(frozen=True)
class TicketAtCreation:
    """What is known about a ticket when it is submitted."""
    created_at: datetime
    priority: str
    subcategory: str
    assigned_team: str
    requester_type: str
    channel: str
    ticket_id: str | None = None  # set only when re-scoring a stored ticket


def sla_hours_for(conn: psycopg.Connection, subcategory: str, priority: str) -> float:
    """The SLA target from the policy table, via the subcategory's ticket type."""
    row = conn.execute(
        "SELECT p.sla_hours FROM subcategories AS s "
        "JOIN sla_policies AS p ON p.ticket_type = s.ticket_type AND p.priority = %s "
        "WHERE s.subcategory = %s",
        [priority, subcategory],
    ).fetchone()
    if row is None:
        known = conn.execute("SELECT 1 FROM subcategories WHERE subcategory = %s", [subcategory]).fetchone()
        if known is None:
            raise InvalidTicket(f"unknown subcategory {subcategory!r}")
        raise InvalidTicket(f"no SLA policy for priority {priority} on subcategory {subcategory!r}")
    return float(row[0])


def features_for(conn: psycopg.Connection, ticket: TicketAtCreation) -> pd.DataFrame:
    """One-row feature matrix for the model, in training column order and types."""
    database_part = read_sql(conn, QUERY, {
        "created_at": ticket.created_at,
        "assigned_team": ticket.assigned_team,
        "subcategory": ticket.subcategory,
        "ticket_id": ticket.ticket_id,
    })
    if database_part.empty:
        # The query joins the calendar and the team; no row means one of them is unknown.
        team = conn.execute("SELECT 1 FROM teams WHERE team = %s", [ticket.assigned_team]).fetchone()
        if team is None:
            raise InvalidTicket(f"unknown team {ticket.assigned_team!r}")
        raise InvalidTicket(f"{ticket.created_at:%Y-%m-%d} is outside the calendar covered by the data")

    row = database_part.assign(
        priority=ticket.priority,
        subcategory=ticket.subcategory,
        assigned_team=ticket.assigned_team,
        requester_type=ticket.requester_type,
        channel=ticket.channel,
        sla_hours=sla_hours_for(conn, ticket.subcategory, ticket.priority),
    )
    return feature_matrix(row[config.FEATURES])
