"""Scoring endpoints: a new ticket, a batch of new tickets, or a stored ticket."""

import pandas as pd
from fastapi import APIRouter, HTTPException, Request

from opspilot.analysis.data import read_sql
from opspilot.api.schemas import BatchPrediction, BatchRequest, Prediction, TicketRequest, TicketRisk
from opspilot.api.scoring import score
from opspilot.modeling import config
from opspilot.modeling.dataset import feature_matrix
from opspilot.modeling.online_features import InvalidTicket, TicketAtCreation, features_for

router = APIRouter(tags=["predictions"])


@router.post("/predictions", response_model=Prediction,
             responses={422: {"description": "Invalid input, or a ticket that cannot be scored"}})
def predict(ticket: TicketRequest, request: Request):
    """Score a new ticket at the moment it is created.

    Features that depend on the queue (backlog, recent similar tickets,
    recent breach rates) are computed from the database as of `created_at`,
    with the same rules used in training.
    """
    state = request.app.state
    try:
        with state.pool.connection() as conn:
            features = features_for(conn, TicketAtCreation(**ticket.model_dump()))
    except InvalidTicket as error:
        raise HTTPException(status_code=422, detail=str(error))
    return score(state.model, state.metadata["threshold"], state.metadata["model"], features)


@router.post("/predictions/batch", response_model=BatchPrediction,
             responses={422: {"description": "Invalid input, or a ticket that cannot be scored"}})
def predict_batch(batch: BatchRequest, request: Request):
    """Score up to 48 new tickets in one request, without reasons.

    Built for comparisons such as the same ticket at every hour of the day.
    Risks are identical to POST /predictions for each ticket; reasons are
    left out to keep the request fast.
    """
    state = request.app.state
    rows = []
    with state.pool.connection() as conn:
        for position, ticket in enumerate(batch.tickets):
            try:
                rows.append(features_for(conn, TicketAtCreation(**ticket.model_dump())))
            except InvalidTicket as error:
                raise HTTPException(status_code=422, detail=f"ticket {position}: {error}")
    risks = state.model.predict_proba(pd.concat(rows, ignore_index=True))[:, 1]
    threshold = state.metadata["threshold"]
    return {"threshold": threshold, "model": state.metadata["model"],
            "risks": [{"risk": float(risk), "flagged": bool(risk >= threshold)} for risk in risks]}


@router.get("/tickets/{ticket_id}/risk", response_model=TicketRisk,
            responses={404: {"description": "No ticket with this id"}})
def ticket_risk(ticket_id: str, request: Request):
    """Score a stored ticket from the features it had when it was created."""
    state = request.app.state
    with state.pool.connection() as conn:
        row = read_sql(conn, "SELECT f.*, t.status FROM ticket_features AS f "
                             "JOIN tickets AS t USING (ticket_id) WHERE f.ticket_id = %s", [ticket_id])
    if row.empty:
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id!r} not found")
    prediction = score(state.model, state.metadata["threshold"], state.metadata["model"],
                       feature_matrix(row[config.FEATURES]))
    outcome = row["sla_breached"].iloc[0]
    return {**prediction, "ticket_id": ticket_id, "created_at": row["created_at"].iloc[0].to_pydatetime(),
            "status": row["status"].iloc[0], "sla_breached": None if outcome is pd.NA else bool(outcome)}
