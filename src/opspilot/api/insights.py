"""AI explanations of scored tickets.

These are POST requests because each one spends money on the Claude API. The
explanation is written from what was known when the ticket was created, so a
stored ticket's real outcome is never part of it.
"""

from fastapi import APIRouter, HTTPException, Request

from opspilot.ai.explain import ExplanationUnavailable
from opspilot.api.predictions import score_new_ticket, score_stored_ticket
from opspilot.api.schemas import Explanation, TicketRequest

router = APIRouter(tags=["insights"])


def explain(request: Request, prediction: dict, created_at) -> dict:
    explainer = request.app.state.explainer
    if explainer is None:
        raise HTTPException(status_code=503, detail="AI explanations are off because no API key is set.")
    try:
        return explainer.explain(prediction, created_at)
    except ExplanationUnavailable as error:
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
