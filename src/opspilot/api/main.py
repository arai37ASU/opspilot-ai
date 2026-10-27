"""OpsPilot API.

Run locally with:
    uvicorn opspilot.api.main:app --reload

Interactive documentation is served at /docs.

The model and a database connection pool are created once when the app
starts, not per request: loading the pipeline takes time, and opening a new
database connection for every request is slow.
"""

import json
from contextlib import asynccontextmanager

import joblib
import pandas as pd
import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool

from opspilot.analysis.data import read_sql
from opspilot.api.schemas import Health, HeldOutMetrics, ModelInfo, Prediction, TicketRequest, TicketRisk
from opspilot.api import metrics
from opspilot.api.scoring import score
from opspilot.api.settings import Settings
from opspilot.modeling import config
from opspilot.modeling.dataset import feature_matrix
from opspilot.modeling.online_features import InvalidTicket, TicketAtCreation, features_for

MODEL_FILE = "sla_breach_model.joblib"
METADATA_FILE = "sla_breach_model.json"
TEST_RESULTS_FILE = "test_results.json"


def load_model_files(settings: Settings) -> tuple:
    """The fitted pipeline, its metadata, and its test results. Fails at startup
    with an explanation rather than on the first request."""
    missing = [path for path in (settings.model_dir / MODEL_FILE, settings.model_dir / METADATA_FILE,
                                 settings.reports_dir / TEST_RESULTS_FILE) if not path.exists()]
    if missing:
        raise RuntimeError(f"missing {', '.join(map(str, missing))}; run `python -m opspilot.modeling.train` first")
    model = joblib.load(settings.model_dir / MODEL_FILE)
    metadata = json.loads((settings.model_dir / METADATA_FILE).read_text())
    test_results = json.loads((settings.reports_dir / TEST_RESULTS_FILE).read_text())
    return model, metadata, test_results


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings or Settings.from_env()
        app.state.model, app.state.metadata, app.state.test_results = load_model_files(config)
        # Autocommit, so read-only requests never leave a transaction open.
        app.state.pool = ConnectionPool(config.database_url, min_size=1, max_size=config.pool_max_size,
                                        kwargs={"autocommit": True}, open=True)
        yield
        app.state.pool.close()

    app = FastAPI(
        title="OpsPilot API",
        description="SLA breach risk for service-desk tickets, and verified operational metrics.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(metrics.router)

    @app.get("/health", response_model=Health, tags=["service"])
    def health(request: Request):
        """Whether the database answers and the model is loaded. Returns 503 if not."""
        try:
            with request.app.state.pool.connection(timeout=2) as conn:
                conn.execute("SELECT 1")
            database = "ok"
        except (psycopg.Error, TimeoutError) as error:
            database = f"unavailable: {type(error).__name__}"
        body = Health(status="ok" if database == "ok" else "degraded", database=database,
                      model_loaded=request.app.state.model is not None)
        return JSONResponse(body.model_dump(), status_code=200 if body.status == "ok" else 503)

    @app.get("/model", response_model=ModelInfo, tags=["model"])
    def model_info(request: Request):
        """The deployed model, its threshold, and how it performed on the held-out test period."""
        metadata, results = request.app.state.metadata, request.app.state.test_results
        selected = results["selected"]
        at_threshold = selected["at_threshold"]
        return ModelInfo(
            model=metadata["model"],
            threshold=metadata["threshold"],
            features=metadata["features"],
            train_period=metadata["train_period"],
            commit=metadata["git"]["commit"],
            test_period=results["test_period"],
            test_metrics=HeldOutMetrics(
                average_precision=selected["average_precision"],
                roc_auc=selected["roc_auc"],
                brier=selected["brier"],
                expected_calibration_error=selected["expected_calibration_error"],
                share_flagged=at_threshold["share_flagged"],
                precision_at_threshold=at_threshold["precision"],
                recall_at_threshold=at_threshold["recall"],
            ),
        )

    @app.post("/predictions", response_model=Prediction, tags=["predictions"],
              responses={422: {"description": "Invalid input, or a ticket that cannot be scored"}})
    def predict(ticket: TicketRequest, request: Request):
        """Score a new ticket at the moment it is created.

        Features that depend on the queue (backlog, recent similar tickets,
        recent breach rates) are computed from the database as of
        `created_at`, with the same rules used in training.
        """
        state = request.app.state
        try:
            with state.pool.connection() as conn:
                features = features_for(conn, TicketAtCreation(**ticket.model_dump()))
        except InvalidTicket as error:
            raise HTTPException(status_code=422, detail=str(error))
        return score(state.model, state.metadata["threshold"], state.metadata["model"], features)

    @app.get("/tickets/{ticket_id}/risk", response_model=TicketRisk, tags=["predictions"],
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

    return app


app = create_app()
