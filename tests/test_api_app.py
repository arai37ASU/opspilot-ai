"""Tests for the API's startup, health check, and model information.

Uses the api_model_dir and client fixtures from conftest.py.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opspilot.api.main import create_app
from opspilot.api.settings import Settings

pytestmark = pytest.mark.db

REPORTS_DIR = Path("reports/modeling")


def test_health_reports_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "model_loaded": True}


def test_health_returns_503_when_the_database_is_unreachable(api_model_dir):
    settings = Settings(database_url="postgresql://nobody:wrong@127.0.0.1:1/none", model_dir=api_model_dir,
                        reports_dir=REPORTS_DIR)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["model_loaded"] is True


def test_model_info_comes_from_saved_files(client):
    body = client.get("/model").json()
    saved = json.loads((REPORTS_DIR / "test_results.json").read_text())
    assert body["model"] == "xgboost"
    assert body["threshold"] == 0.457
    assert body["test_metrics"]["average_precision"] == saved["selected"]["average_precision"]
    assert body["test_metrics"]["share_flagged"] == saved["selected"]["at_threshold"]["share_flagged"]
    assert body["test_period"] == saved["test_period"]


def test_startup_fails_clearly_without_a_model(tmp_path, test_database_url):
    settings = Settings(database_url=test_database_url, model_dir=tmp_path, reports_dir=REPORTS_DIR)
    with pytest.raises(RuntimeError, match="opspilot.modeling.train"):
        with TestClient(create_app(settings)):
            pass


def test_openapi_documents_the_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/health", "/model", "/predictions", "/tickets/{ticket_id}/risk"} <= set(paths)
