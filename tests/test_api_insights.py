"""The explanation endpoints, with the explainer replaced so nothing calls Claude."""

import pytest

from opspilot.ai.client import AIUnavailable

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
    use_explainer(RecordingExplainer(AIUnavailable("Try again shortly.")))
    response = client.post("/explanations", json=TICKET)
    assert response.status_code == 503
    assert response.json()["detail"] == "Try again shortly."


BRIEFING = {"headline": "h", "findings": [], "actions": [], "caveats": [], "facts": {}, "model": "claude-test",
            "attempts": 1, "usage": {"input_tokens": 1, "output_tokens": 1}}


class RecordingBriefer:
    def __init__(self):
        self.facts = None

    def brief(self, facts):
        self.facts = facts
        return BRIEFING


@pytest.fixture
def briefer(client, monkeypatch):
    recording = RecordingBriefer()
    monkeypatch.setattr(client.app.state, "briefer", recording)
    return recording


def post_period(client, start, end):
    return client.post("/briefings", json={"start": start, "end": end})


def test_briefing_says_so_without_a_key(client, monkeypatch):
    monkeypatch.setattr(client.app.state, "briefer", None)
    response = post_period(client, "2025-09-01", "2025-09-30")
    assert response.status_code == 503
    assert "no API key" in response.json()["detail"]


def test_briefing_facts_match_the_dashboard_metrics(client, briefer):
    assert post_period(client, "2025-03-01", "2025-03-31").status_code == 200
    overview = client.get("/metrics/overview", params={"start": "2025-03-01", "end": "2025-03-31"}).json()
    facts = briefer.facts["overview"]
    assert facts["tickets_created"] == f"{overview['tickets']:,}"
    assert facts["breach_rate"] == f"{overview['breach_rate_pct']:.1f}%"


def test_briefing_compares_with_the_same_dates_a_year_earlier(client, briefer):
    post_period(client, "2025-03-01", "2025-03-31")
    earlier = client.get("/metrics/overview", params={"start": "2024-03-01", "end": "2024-03-31"}).json()
    comparison = briefer.facts["comparison"]
    assert "01 March 2024" in comparison["compared_with"]
    assert comparison["tickets_then"] == f"{earlier['tickets']:,}"
    assert "breach_rate_change" in comparison


def test_briefing_finds_incidents_in_its_period_only(client, briefer):
    post_period(client, "2025-03-01", "2025-03-31")
    incidents = briefer.facts["spikes"]["suspected_incidents"]
    assert [(i["issue"], i["tickets"]) for i in incidents] == [("phishing report", "67")]


def test_a_period_at_the_end_of_the_data_drops_the_misleading_comparison(client, briefer):
    post_period(client, "2025-12-01", "2025-12-31")
    assert "breach_rate_change" not in briefer.facts["comparison"]
    assert "tickets_change" in briefer.facts["comparison"]
    assert any("still open" in caveat for caveat in briefer.facts["caveats"])


def test_a_period_without_a_year_earlier_says_so(client, briefer):
    post_period(client, "2024-03-01", "2024-03-31")
    assert "comparison" not in briefer.facts
    assert any("no comparison" in caveat for caveat in briefer.facts["caveats"])


def test_invalid_periods_are_rejected_before_anything_is_spent(client, briefer):
    assert post_period(client, "2025-03-31", "2025-03-01").status_code == 422
    assert post_period(client, "2030-01-01", "2030-01-31").status_code == 422
    assert briefer.facts is None
