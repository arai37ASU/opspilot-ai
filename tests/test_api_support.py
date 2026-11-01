"""Tests for the endpoints that support the dashboard: /reference,
/predictions/batch, /metrics/daily, /metrics/spikes and /model/evaluation."""

from datetime import date

import pytest

from opspilot.api.metrics import group_spikes

pytestmark = pytest.mark.db

TICKET = {
    "created_at": "2025-09-03T19:30:00",
    "priority": "P2",
    "subcategory": "projector_display",
    "assigned_team": "Classroom Technology",
    "requester_type": "faculty",
    "channel": "phone",
}


# --- /reference ---------------------------------------------------------------


@pytest.fixture(scope="module")
def reference(client):
    return client.get("/reference").json()


def test_reference_lists_the_catalogue_and_the_date_range(reference, db_conn):
    assert reference["date_range"] == {"start": "2024-01-01", "end": "2025-12-31"}
    assert len(reference["subcategories"]) == db_conn.execute("SELECT count(*) FROM subcategories").fetchone()[0]
    assert len(reference["teams"]) == 7
    assert reference["priorities"] == ["P1", "P2", "P3", "P4"]
    assert "walk_in" in reference["channels"]


def test_allowed_priorities_follow_the_sla_policies(reference):
    by_name = {row["subcategory"]: row for row in reference["subcategories"]}
    assert by_name["password_reset"]["ticket_type"] == "service_request"
    assert by_name["password_reset"]["allowed_priorities"] == ["P2", "P3", "P4"]
    assert by_name["network_outage"]["allowed_priorities"] == ["P1", "P2", "P3", "P4"]


def test_every_option_the_reference_offers_can_be_scored(client, reference):
    """A client that only offers the listed options can never build a ticket the API rejects."""
    first = reference["subcategories"][0]
    for priority in first["allowed_priorities"]:
        ticket = {**TICKET, "subcategory": first["subcategory"], "assigned_team": first["owning_team"], "priority": priority}
        assert client.post("/predictions", json=ticket).status_code == 200


# --- /predictions/batch ----------------------------------------------------------


def hours_of(ticket):
    return [{**ticket, "created_at": f"2025-09-03T{hour:02d}:30:00"} for hour in range(24)]


def test_batch_scores_match_single_predictions(client):
    tickets = hours_of(TICKET)
    batch = client.post("/predictions/batch", json={"tickets": tickets}).json()
    assert len(batch["risks"]) == 24
    for ticket, result in zip(tickets[::6], batch["risks"][::6]):
        single = client.post("/predictions", json=ticket).json()
        assert result["risk"] == pytest.approx(single["risk"], abs=1e-9)
        assert result["flagged"] == single["flagged"]


def test_batch_shows_the_evening_effect(client):
    risks = [r["risk"] for r in client.post("/predictions/batch", json={"tickets": hours_of(TICKET)}).json()["risks"]]
    assert max(risks[18:22]) > 2 * min(risks[9:12])  # evening arrivals against late morning


@pytest.mark.parametrize("count", [0, 49])
def test_batch_size_is_limited(client, count):
    assert client.post("/predictions/batch", json={"tickets": [TICKET] * count}).status_code == 422


def test_batch_reports_which_ticket_is_invalid(client):
    tickets = [TICKET] * 3 + [{**TICKET, "subcategory": "teleportation"}]
    response = client.post("/predictions/batch", json={"tickets": tickets})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("ticket 3: unknown subcategory")


# --- /metrics/daily ----------------------------------------------------------------


def test_daily_has_one_row_per_calendar_day(client):
    days = client.get("/metrics/daily").json()
    assert len(days) == 731
    assert days[0]["day"] == "2024-01-01" and days[-1]["day"] == "2025-12-31"


def test_daily_totals_match_the_overview(client):
    params = {"start": "2025-09-01", "end": "2025-09-30"}
    days = client.get("/metrics/daily", params=params).json()
    overview = client.get("/metrics/overview", params=params).json()
    assert len(days) == 30
    assert sum(day["tickets"] for day in days) == overview["tickets"]


def test_daily_marks_weekends_and_semester_starts(client):
    days = {day["day"]: day for day in client.get("/metrics/daily").json()}
    assert days["2025-09-06"]["is_weekend"] is True        # a Saturday
    assert days["2024-08-26"]["academic_period"] == "semester_start"
    assert days["2024-07-04"]["is_holiday"] is True


# --- /model/evaluation ---------------------------------------------------------


@pytest.fixture(scope="module")
def evaluation(client):
    response = client.get("/model/evaluation")
    assert response.status_code == 200
    return response.json()


def test_evaluation_matches_the_saved_test_results(client, evaluation):
    held_out = client.get("/model").json()["test_metrics"]
    assert evaluation["average_precision"] == held_out["average_precision"]
    assert evaluation["at_threshold"]["recall"] == held_out["recall_at_threshold"]


def test_confusion_counts_and_calibration_bands_cover_every_test_ticket(evaluation):
    counts = evaluation["at_threshold"]
    total = counts["true_positives"] + counts["false_positives"] + counts["false_negatives"] + counts["true_negatives"]
    assert total == evaluation["test_tickets"]
    assert sum(band["n"] for band in evaluation["calibration"]) == evaluation["test_tickets"]


def test_comparison_marks_only_the_deployed_model(evaluation):
    selected = [row for row in evaluation["comparison"] if row["selected"]]
    assert len(selected) == 1
    assert selected[0]["average_precision"] == evaluation["average_precision"]


def test_feature_importance_covers_the_model_features(client, evaluation):
    features = client.get("/model").json()["features"]
    assert {row["feature"] for row in evaluation["feature_importance"]} == set(features)


def test_example_tickets_exist_and_fall_in_the_test_period(client, evaluation):
    assert {example["case"] for example in evaluation["examples"]} == {"caught_breach", "false_alarm", "missed_breach"}
    test_start = evaluation["test_period"][0][:10]
    for example in evaluation["examples"]:
        ticket = client.get(f"/tickets/{example['ticket_id']}/risk").json()
        assert ticket["created_at"][:10] >= test_start
        assert ticket["sla_breached"] == example["breached"]


# --- /metrics/spikes -----------------------------------------------------------


def spike(day, subcategory, tickets=20, peak=5):
    return {"day": date.fromisoformat(day), "academic_period": "regular", "subcategory": subcategory,
            "tickets": tickets, "typical_daily": 1.0, "peak_two_hours": peak}


def test_days_close_together_form_one_episode():
    _, episodes = group_spikes([spike("2025-03-18", "phishing_report", 37, 9), spike("2025-03-19", "phishing_report", 30, 12)])
    assert len(episodes) == 1
    assert episodes[0]["kind"] == "one_off"
    assert episodes[0]["tickets"] == 67
    assert episodes[0]["peak_two_hours"] == 12
    assert (episodes[0]["start"], episodes[0]["end"]) == (date(2025, 3, 18), date(2025, 3, 19))


def test_an_issue_that_comes_back_is_recurring():
    days, episodes = group_spikes([spike("2024-09-03", "password_reset"), spike("2025-01-14", "password_reset"),
                                   spike("2025-03-18", "phishing_report")])
    assert {d["subcategory"]: d["kind"] for d in days} == {"password_reset": "recurring", "phishing_report": "one_off"}
    assert [e["subcategory"] for e in episodes] == ["password_reset", "password_reset", "phishing_report"]


def test_days_more_than_a_week_apart_are_separate_episodes():
    _, episodes = group_spikes([spike("2024-01-01", "wifi_connectivity"), spike("2024-01-09", "wifi_connectivity")])
    assert len(episodes) == 2


def test_no_spikes_gives_empty_lists():
    assert group_spikes([]) == ([], [])


def test_spikes_endpoint_finds_the_four_planted_incidents(client):
    body = client.get("/metrics/spikes").json()
    assert len(body["days"]) == 24
    incidents = [e for e in body["episodes"] if e["kind"] == "one_off"]
    assert [(e["subcategory"], e["start"], e["end"], e["tickets"]) for e in incidents] == [
        ("wifi_connectivity", "2024-02-13", "2024-02-13", 52),
        ("lecture_capture", "2024-09-04", "2024-09-04", 33),
        ("phishing_report", "2025-03-18", "2025-03-19", 67),
        ("network_outage", "2025-10-07", "2025-10-07", 40),
    ]
    recurring = {d["subcategory"] for d in body["days"] if d["kind"] == "recurring"}
    assert recurring == {"password_reset", "mfa_issue"}
