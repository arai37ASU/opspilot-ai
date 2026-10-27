"""Tests for POST /predictions and GET /tickets/{ticket_id}/risk."""

from datetime import datetime

import joblib
import numpy as np
import pytest

from opspilot.analysis.data import read_sql
from opspilot.modeling import config
from opspilot.modeling.dataset import feature_matrix
from opspilot.modeling.online_features import TicketAtCreation, features_for

pytestmark = pytest.mark.db

VALID = {
    "created_at": "2025-09-03T19:30:00",
    "priority": "P2",
    "subcategory": "projector_display",
    "assigned_team": "Classroom Technology",
    "requester_type": "faculty",
    "channel": "phone",
}


@pytest.fixture(scope="module")
def model(api_model_dir):
    return joblib.load(api_model_dir / "sla_breach_model.joblib")


def test_prediction_for_a_new_ticket(client):
    response = client.post("/predictions", json=VALID)
    assert response.status_code == 200
    body = response.json()
    assert 0 <= body["risk"] <= 1
    assert body["flagged"] == (body["risk"] >= body["threshold"])
    assert len(body["reasons"]) == 3
    assert set(body["inputs"]) == set(config.FEATURES)
    assert body["inputs"]["hours_until_staffed"] == 12.5  # Wednesday 19:30 -> Thursday 08:00


def test_reasons_are_ordered_and_labelled(client):
    reasons = client.post("/predictions", json=VALID).json()["reasons"]
    sizes = [abs(r["contribution"]) for r in reasons]
    assert sizes == sorted(sizes, reverse=True)
    for reason in reasons:
        assert reason["direction"] == ("raises risk" if reason["contribution"] > 0 else "lowers risk")


def test_prediction_uses_the_serving_features_and_the_loaded_model(client, db_conn, model):
    ticket = TicketAtCreation(**{**VALID, "created_at": datetime.fromisoformat(VALID["created_at"])})
    expected = model.predict_proba(features_for(db_conn, ticket))[0, 1]
    assert client.post("/predictions", json=VALID).json()["risk"] == pytest.approx(float(expected), abs=1e-12)


def test_an_evening_p2_is_riskier_than_the_same_ticket_in_the_morning(client):
    evening = client.post("/predictions", json=VALID).json()["risk"]
    morning = client.post("/predictions", json={**VALID, "created_at": "2025-09-03T09:30:00"}).json()["risk"]
    assert evening > morning


@pytest.mark.parametrize("changes", [
    {"priority": "P9"},
    {"channel": "fax"},
    {"created_at": "not a date"},
])
def test_invalid_fields_are_rejected_by_validation(client, changes):
    response = client.post("/predictions", json={**VALID, **changes})
    assert response.status_code == 422


def test_missing_fields_are_rejected(client):
    body = {key: value for key, value in VALID.items() if key != "subcategory"}
    assert client.post("/predictions", json=body).status_code == 422


@pytest.mark.parametrize("changes, message", [
    ({"subcategory": "teleportation"}, "unknown subcategory"),
    ({"assigned_team": "Facilities"}, "unknown team"),
    ({"subcategory": "password_reset", "priority": "P1"}, "no SLA policy"),
    ({"created_at": "2031-01-01T09:00:00"}, "outside the calendar"),
])
def test_tickets_that_cannot_be_scored_get_a_clear_422(client, changes, message):
    response = client.post("/predictions", json={**VALID, **changes})
    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_risk_for_a_stored_ticket_matches_the_model_on_its_stored_features(client, db_conn, model):
    row = read_sql(db_conn, "SELECT * FROM ticket_features WHERE ticket_id = 'TKT-030000'")
    expected = model.predict_proba(feature_matrix(row[config.FEATURES]))[0, 1]
    body = client.get("/tickets/TKT-030000/risk").json()
    assert body["risk"] == pytest.approx(float(expected), abs=1e-12)
    assert body["ticket_id"] == "TKT-030000"
    assert body["status"] == "resolved"
    assert isinstance(body["sla_breached"], bool)


def test_unresolved_ticket_has_no_known_outcome(client, db_conn):
    ticket_id = db_conn.execute("SELECT ticket_id FROM tickets WHERE status = 'open' LIMIT 1").fetchone()[0]
    body = client.get(f"/tickets/{ticket_id}/risk").json()
    assert body["status"] == "open"
    assert body["sla_breached"] is None


def test_unknown_ticket_returns_404(client):
    response = client.get("/tickets/TKT-999999/risk")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_scores_vary_across_tickets(client):
    risks = [client.get(f"/tickets/TKT-0{n}/risk").json()["risk"] for n in range(30000, 30040)]
    assert np.std(risks) > 0.01
