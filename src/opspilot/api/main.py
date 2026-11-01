"""OpsPilot API.

Run locally with:
    uvicorn opspilot.api.main:app --reload

The dashboard is served at / and interactive API documentation at /docs.

The model and a database connection pool are created once when the app
starts, not per request: loading the pipeline takes time, and opening a new
database connection for every request is slow.

This module assembles the app; endpoints live in their own modules
(predictions, metrics, reference).
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import joblib
import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool

from opspilot.ai.briefing import Briefer
from opspilot.ai.client import build_client
from opspilot.ai.explain import TicketExplainer
from opspilot.api import evaluation, insights, metrics, predictions, reference
from opspilot.api.schemas import Health, HeldOutMetrics, ModelInfo
from opspilot.api.settings import Settings

MODEL_FILE = "sla_breach_model.joblib"
METADATA_FILE = "sla_breach_model.json"
TEST_RESULTS_FILE = "test_results.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class DashboardFiles(StaticFiles):
    """Static files the browser must recheck before reusing.

    Without a cache rule, browsers guess how long a file stays fresh and can
    run old JavaScript after a deploy. "no-cache" still allows caching: an
    unchanged file comes back as a small 304 response.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


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
        active = settings or Settings.from_env()
        app.state.model, app.state.metadata, app.state.test_results = load_model_files(active)
        app.state.evaluation = evaluation.load_evaluation(active.reports_dir)
        client = build_client()
        app.state.explainer = TicketExplainer(client, active.ai_model) if client else None
        app.state.briefer = Briefer(client, active.ai_model) if client else None
        # Autocommit, so read-only requests never leave a transaction open.
        app.state.pool = ConnectionPool(active.database_url, min_size=1, max_size=active.pool_max_size,
                                        kwargs={"autocommit": True}, open=True)
        yield
        app.state.pool.close()

    app = FastAPI(
        title="OpsPilot API",
        description="SLA breach risk for service-desk tickets, and verified operational metrics.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(predictions.router)
    app.include_router(metrics.router)
    app.include_router(reference.router)
    app.include_router(evaluation.router)
    app.include_router(insights.router)

    # The dashboard: one HTML page plus its CSS, JavaScript and chart library,
    # served from the same origin as the API so the browser needs no
    # cross-origin setup.
    app.mount("/static", DashboardFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

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

    return app


app = create_app()
