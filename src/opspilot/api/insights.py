"""AI explanations of scored tickets, and management briefings.

These are POST requests because each one spends money on the Claude API. A
ticket's explanation is written from what was known when it was created, so a
stored ticket's real outcome is never part of it.
"""

from fastapi import APIRouter, HTTPException, Request

from opspilot.ai.briefing import briefing_facts, year_earlier
from opspilot.ai.client import AIUnavailable
from opspilot.api.metrics import all_spikes, date_range, period_overview, period_teams
from opspilot.api.predictions import score_new_ticket, score_stored_ticket
from opspilot.api.schemas import Briefing, BriefingRequest, Explanation, TicketRequest

router = APIRouter(tags=["insights"])


def explain(request: Request, prediction: dict, created_at) -> dict:
    explainer = request.app.state.explainer
    if explainer is None:
        raise HTTPException(status_code=503, detail="AI explanations are off because no API key is set.")
    try:
        return explainer.explain(prediction, created_at)
    except AIUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error))


@router.post("/explanations", response_model=Explanation,
             responses={503: {"description": "No API key is set, or no verified explanation could be produced"}})
def explain_new_ticket(ticket: TicketRequest, request: Request):
    """Score a new ticket and explain the result in plain language."""
    return explain(request, score_new_ticket(ticket, request), ticket.created_at)


@router.post("/tickets/{ticket_id}/explanation", response_model=Explanation,
             responses={404: {"description": "No ticket with this id"},
                        503: {"description": "No API key is set, or no verified explanation could be produced"}})
def explain_stored_ticket(ticket_id: str, request: Request):
    """Score a stored ticket and explain the result in plain language."""
    scored = score_stored_ticket(ticket_id, request)
    return explain(request, scored, scored["created_at"])


@router.post("/briefings", response_model=Briefing,
             responses={422: {"description": "A reversed date range, or a period with no tickets"},
                        503: {"description": "No API key is set, or no verified briefing could be produced"}})
def write_briefing(period: BriefingRequest, request: Request):
    """A short management briefing for a date range, from the verified metrics."""
    state = request.app.state
    if state.briefer is None:
        raise HTTPException(status_code=503, detail="AI briefings are off because no API key is set.")
    with state.pool.connection() as conn:
        start, end = date_range(conn, period.start, period.end)
        first_day, last_day = date_range(conn, None, None)
        current = period_overview(conn, start, end)
        if current["tickets"] == 0:
            raise HTTPException(status_code=422, detail="There are no tickets in this period.")
        dates = year_earlier(start, end, first_day)
        earlier = period_overview(conn, *dates) if dates else None
        teams = period_teams(conn, start, end)
        days, episodes = all_spikes(conn)
    facts = briefing_facts(current, earlier, teams, days, episodes, last_day)
    try:
        return state.briefer.brief(facts)
    except AIUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error))
