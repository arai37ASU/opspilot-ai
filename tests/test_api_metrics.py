"""Tests for the /metrics endpoints.

The KPI endpoints use their own SQL (sql/api/metrics.sql). Over the full date
range they must agree with the Phase 3 analysis results saved in reports/sql,
which were computed by different queries and cross-checked against pandas.
"""

from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.db

SAVED = Path("reports/sql")


def saved(name: str) -> pd.DataFrame:
    return pd.read_csv(SAVED / f"{name}.csv")


def test_overview_matches_the_saved_analysis(client):
    body = client.get("/metrics/overview").json()
    overall = saved("01_sla_compliance__overall").iloc[0]
    assert (body["tickets"], body["resolved"], body["breached"]) == (overall["tickets"], overall["resolved"], overall["breached"])
    assert body["breach_rate_pct"] == overall["breach_rate_pct"]
    assert body["start"] == "2024-01-01" and body["end"] == "2025-12-31"


def test_priority_breakdown_matches_the_saved_analysis(client):
    by_priority = {row["priority"]: row for row in client.get("/metrics/overview").json()["by_priority"]}
    for row in saved("01_sla_compliance__by_priority").itertuples():
        assert by_priority[row.priority]["breach_rate_pct"] == row.breach_rate_pct
        assert by_priority[row.priority]["resolved"] == row.resolved


def test_team_metrics_match_the_saved_analysis(client):
    teams = {row["team"]: row for row in client.get("/metrics/teams").json()["teams"]}
    assert len(teams) == 7
    for row in saved("01_sla_compliance__by_team").itertuples():
        assert teams[row.team]["breach_rate_pct"] == row.breach_rate_pct
        assert teams[row.team]["resolved"] == row.resolved
    for row in saved("02_team_workload__tickets_per_agent").itertuples():
        assert teams[row.team]["tickets"] == row.tickets


def test_trend_matches_the_saved_analysis(client):
    trend = pd.DataFrame(client.get("/metrics/trend").json())
    expected = saved("01_sla_compliance__monthly_trend")
    assert trend["tickets"].tolist() == expected["tickets"].tolist()
    assert trend["breach_rate_pct"].tolist() == expected["breach_rate_pct"].tolist()


def test_date_filter_narrows_the_results(client):
    full = client.get("/metrics/overview").json()
    one_month = client.get("/metrics/overview", params={"start": "2025-09-01", "end": "2025-09-30"}).json()
    assert 0 < one_month["tickets"] < full["tickets"]
    trend = {row["month"]: row for row in client.get("/metrics/trend").json()}
    assert one_month["tickets"] == trend["2025-09-01"]["tickets"]


def test_an_empty_range_returns_zeros_not_an_error(client):
    body = client.get("/metrics/overview", params={"start": "2030-01-01", "end": "2030-01-31"}).json()
    assert body["tickets"] == 0
    assert body["breach_rate_pct"] is None
    assert body["by_priority"] == []


def test_reversed_dates_are_rejected(client):
    response = client.get("/metrics/overview", params={"start": "2025-09-30", "end": "2025-09-01"})
    assert response.status_code == 422
    assert "after" in response.json()["detail"]


def test_invalid_date_is_rejected(client):
    assert client.get("/metrics/teams", params={"start": "September"}).status_code == 422


def test_analysis_catalog_lists_every_saved_query(client):
    catalog = client.get("/metrics/analysis").json()
    assert len(catalog) == len(list(SAVED.glob("*.csv")))
    assert all(entry["path"].startswith("/metrics/analysis/") for entry in catalog)
    assert all(entry["description"] for entry in catalog)  # every entry says what it answers
    overall = next(e for e in catalog if e["path"] == "/metrics/analysis/01_sla_compliance/overall")
    assert overall["description"].startswith("How often do resolved tickets meet their SLA target")


def test_analysis_query_returns_the_saved_rows(client):
    body = client.get("/metrics/analysis/03_after_hours/by_arrival_window").json()
    rows = pd.DataFrame(body["rows"])
    expected = saved("03_after_hours__by_arrival_window")
    pd.testing.assert_frame_equal(rows[expected.columns], expected, check_dtype=False)


def test_unknown_analysis_query_returns_404(client):
    response = client.get("/metrics/analysis/01_sla_compliance/no_such_query")
    assert response.status_code == 404
    assert "/metrics/analysis" in response.json()["detail"]
