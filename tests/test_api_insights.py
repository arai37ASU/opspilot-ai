"""The explanation endpoints, with the explainer replaced so nothing calls Claude."""

import pytest

from opspilot.ai.explain import ExplanationUnavailable

pytestmark = pytest.mark.db

TICKET = {
    "created_at": "2025-09-03T19:30:00", "priority": "P2", "subcategory": "projector_display",
    "assigned_team": "Classroom Technology", "requester_type": "faculty", "channel": "phone",
}
RESULT = {"summary": "s", "reasons": [], "suggested_action": "a", "risk": 0.5, "flagged": True, "threshold": 0.457,
          "model": "claude-test", "attempts": 1, "usage": {"input_tokens": 1, "output_tokens": 1}}


class RecordingExplainer:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def explain(self, prediction, created_at):
        self.calls.append((prediction, created_at))
        if self.error:
            raise self.error
        return RESULT


@pytest.fixture
def use_explainer(client, monkeypatch):
    def install(explainer):
        monkeypatch.setattr(client.app.state, "explainer", explainer)
        return explainer
    return install


def test_without_a_key_explanations_say_so_and_scoring_still_works(client, use_explainer):
    use_explainer(None)
    response = client.post("/explanations", json=TICKET)
    assert response.status_code == 503
    assert "no API key" in response.json()["detail"]
    assert client.post("/predictions", json=TICKET).status_code == 200


def test_new_ticket_is_scored_then_explained(client, use_explainer):
    explainer = use_explainer(RecordingExplainer())
    assert client.post("/explanations", json=TICKET).status_code == 200
    prediction, created_at = explainer.calls[0]
    assert prediction["inputs"]["priority"] == "P2"
    assert created_at.hour == 19


def test_stored_ticket_is_explained(client, use_explainer):
    explainer = use_explainer(RecordingExplainer())
    assert client.post("/tickets/TKT-041779/explanation").status_code == 200
    assert explainer.calls[0][0]["ticket_id"] == "TKT-041779"


def test_invalid_input_is_rejected_before_anything_is_spent(client, use_explainer):
    explainer = use_explainer(RecordingExplainer())
    assert client.post("/explanations", json={**TICKET, "subcategory": "nope"}).status_code == 422
    assert client.post("/tickets/NOPE/explanation").status_code == 404
    assert explainer.calls == []


def test_a_failed_explanation_returns_its_safe_message(client, use_explainer):
    use_explainer(RecordingExplainer(ExplanationUnavailable("Try again shortly.")))
    response = client.post("/explanations", json=TICKET)
    assert response.status_code == 503
    assert response.json()["detail"] == "Try again shortly."
