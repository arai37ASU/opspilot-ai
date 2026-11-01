"""Reference data for clients: the values a ticket can take.

Read from the database (the service catalogue, teams, SLA policies and the
calendar) and from the request schema, so a client never hard-codes a list
that could drift from what the API accepts.
"""

from typing import get_args

from fastapi import APIRouter, Request

from opspilot.analysis.data import read_sql
from opspilot.api.schemas import Reference, TicketRequest

router = APIRouter(tags=["reference"])


def allowed_values(field: str) -> list[str]:
    """The Literal values a TicketRequest field accepts."""
    return list(get_args(TicketRequest.model_fields[field].annotation))


@router.get("/reference", response_model=Reference)
def reference(request: Request):
    """Options for building a ticket, and the period the data covers."""
    with request.app.state.pool.connection() as conn:
        subcategories = read_sql(conn, """
            SELECT s.subcategory, s.category, s.ticket_type, s.owning_team,
                   array_agg(p.priority ORDER BY p.priority) AS allowed_priorities
            FROM subcategories AS s
            JOIN sla_policies AS p USING (ticket_type)
            GROUP BY s.subcategory, s.category, s.ticket_type, s.owning_team
            ORDER BY s.category, s.subcategory""")
        teams = read_sql(conn, "SELECT team, agents FROM teams ORDER BY team")
        first, last = conn.execute("SELECT min(day), max(day) FROM calendar_days").fetchone()
    return {
        "date_range": {"start": first, "end": last},
        "priorities": allowed_values("priority"),
        "requester_types": allowed_values("requester_type"),
        "channels": allowed_values("channel"),
        "teams": teams.to_dict(orient="records"),
        "subcategories": subcategories.to_dict(orient="records"),
        "threshold": request.app.state.metadata["threshold"],
    }
