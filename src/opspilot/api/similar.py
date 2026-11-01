"""Find past tickets like a stored ticket or a piece of text.

These run locally and cost nothing per request. Results for a stored ticket
only come from before it was created, so nothing here looks into its future.
Text search is a POST so that what someone typed never ends up in a URL or an
access log.
"""

import statistics
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from opspilot.ai.embed_tickets import vector_literal
from opspilot.ai.embeddings import MIN_TEXT_SIMILARITY, embed_texts
from opspilot.analysis.data import read_sql
from opspilot.api.metrics import records
from opspilot.api.schemas import SimilarSearch, SimilarTickets
from opspilot.db.sql_files import parse_named_queries

SQL_FILE = Path(__file__).resolve().parents[3] / "sql" / "api" / "similar_tickets.sql"
QUERIES = {query.name: query.sql for query in parse_named_queries(SQL_FILE.read_text())}
POOL_FACTOR = 10

router = APIRouter(tags=["similar tickets"])


def find_similar(conn, vector: str, before: datetime, limit: int) -> list[dict]:
    params = {"vector": vector, "before": before, "limit": limit, "pool": limit * POOL_FACTOR}
    return records(read_sql(conn, QUERIES["nearest"], params))


def outcome_summary(tickets: list[dict]) -> dict:
    """What happened to the results that have finished, computed here rather than in the page."""
    resolved = [ticket for ticket in tickets if ticket["sla_breached"] is not None]
    hours = [ticket["resolution_hours"] for ticket in resolved if ticket["resolution_hours"] is not None]
    return {"resolved": len(resolved), "breached": sum(bool(ticket["sla_breached"]) for ticket in resolved),
            "median_resolution_hours": round(statistics.median(hours), 1) if hours else None}


@router.get("/tickets/{ticket_id}/similar", response_model=SimilarTickets,
            responses={404: {"description": "No ticket with this id"},
                       503: {"description": "Embeddings have not been built"}})
def similar_to_ticket(ticket_id: str, request: Request, limit: int = Query(5, ge=1, le=20)):
    """Earlier tickets with the most similar descriptions."""
    with request.app.state.pool.connection() as conn:
        row = conn.execute(QUERIES["ticket_embedding"], {"ticket_id": ticket_id}).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"ticket {ticket_id!r} not found")
        vector, created_at = row
        if vector is None:
            raise HTTPException(status_code=503, detail="Embeddings have not been built; run opspilot.ai.embed_tickets.")
        tickets = find_similar(conn, vector, created_at, limit)
    return {"tickets": tickets, "outcomes": outcome_summary(tickets)}


@router.post("/similar-tickets", response_model=SimilarTickets)
def similar_to_text(search: SimilarSearch, request: Request):
    """Past tickets most similar to a description of a problem, in any wording.

    Nearest-neighbour search always finds something, so results below a
    similarity cutoff are dropped: off-topic text returns nothing.
    """
    vector = vector_literal(embed_texts([search.text])[0])
    with request.app.state.pool.connection() as conn:
        found = find_similar(conn, vector, datetime.max, search.limit)
    tickets = [ticket for ticket in found if ticket["similarity"] >= MIN_TEXT_SIMILARITY]
    return {"tickets": tickets, "outcomes": outcome_summary(tickets)}
