"""Tests for the analysis queries.

The main technique is cross-checking: key SQL results are recomputed
independently in pandas from the generated CSV. Two different implementations
agreeing is much stronger evidence than either one alone.
"""

import numpy as np
import pandas as pd
import pytest

from opspilot.data_generation import config
from opspilot.db.analysis import analysis_queries, run_analysis, run_query
from pandas_reference import open_at_arrival

QUERIES = analysis_queries()


def query(file_stem, name):
    return next(q for q in QUERIES[file_stem] if q.name == name)


@pytest.fixture(scope="module")
def tickets(data_dir):
    return pd.read_csv(data_dir / "tickets.csv", parse_dates=["created_at", "resolved_at"])


@pytest.fixture(scope="module")
def resolved(tickets):
    return tickets[tickets["status"] == "resolved"].assign(sla_breached=lambda df: df["sla_breached"].astype(bool))


def test_analysis_files_are_numbered_and_parse():
    assert len(QUERIES) == 9
    for file_stem, queries in QUERIES.items():
        assert file_stem[:2].isdigit(), file_stem
        assert queries, file_stem


# --- Every query runs ----------------------------------------------------------


@pytest.mark.db
@pytest.mark.parametrize(
    "file_stem, name", [(stem, q.name) for stem, queries in QUERIES.items() for q in queries]
)
def test_query_runs_and_returns_rows(db_conn, file_stem, name):
    assert len(run_query(db_conn, query(file_stem, name))) > 0


@pytest.mark.db
def test_runner_writes_one_csv_per_query(db_conn, tmp_path):
    written = run_analysis(db_conn, tmp_path)
    assert len(written) == sum(len(queries) for queries in QUERIES.values())
    assert all(path.exists() for path in written)


# --- Cross-checks against pandas ------------------------------------------------


@pytest.mark.db
def test_overall_and_priority_breach_rates_match_pandas(db_conn, resolved):
    overall = run_query(db_conn, query("01_sla_compliance", "overall")).iloc[0]
    assert overall["resolved"] == len(resolved)
    # Unrounded pandas values, for the rounding reason explained in
    # test_median_resolution_matches_pandas.
    assert float(overall["breach_rate_pct"]) == pytest.approx(100 * resolved["sla_breached"].mean(), abs=0.05 + 1e-9)

    by_priority = run_query(db_conn, query("01_sla_compliance", "by_priority")).set_index("priority")
    expected = 100 * resolved.groupby("priority")["sla_breached"].mean()
    assert by_priority["breach_rate_pct"].astype(float).to_dict() == pytest.approx(expected.to_dict(), abs=0.05 + 1e-9)


def backlog_buckets_in_pandas(tickets):
    """Open tickets per agent at arrival, computed without the event stream."""
    resolved = tickets[tickets["status"] == "resolved"].set_index("ticket_id")
    agents = resolved["assigned_team"].map(config.TEAM_AGENTS)
    open_per_agent = open_at_arrival(tickets).reindex(resolved.index) / agents
    buckets = pd.cut(open_per_agent, [0, 1, 2, 4, 6, np.inf], right=False, labels=["0-1", "1-2", "2-4", "4-6", "6+"])
    return buckets.value_counts().sort_index()


@pytest.mark.db
def test_backlog_buckets_match_independent_pandas_calculation(db_conn, tickets):
    result = run_query(db_conn, query("02_team_workload", "breach_by_backlog")).set_index("open_tickets_per_agent")
    expected = backlog_buckets_in_pandas(tickets)
    assert result["resolved"].to_dict() == {str(k): v for k, v in expected.items()}


@pytest.mark.db
def test_breach_rate_rises_with_backlog(db_conn):
    result = run_query(db_conn, query("02_team_workload", "breach_by_backlog"))
    rates = result["breach_rate_pct"].astype(float).tolist()
    p3_rates = result["p3_breach_rate_pct"].astype(float).tolist()
    assert rates == sorted(rates)
    assert p3_rates == sorted(p3_rates)


@pytest.mark.db
def test_arrival_windows_cover_every_ticket(db_conn, tickets):
    result = run_query(db_conn, query("03_after_hours", "by_arrival_window")).set_index("arrival_window")
    assert result["tickets"].sum() == len(tickets)
    assert float(result["share_of_breaches_pct"].sum()) == pytest.approx(100, abs=0.2)

    created = tickets["created_at"]
    holidays = created.dt.date.isin(config.HOLIDAYS)
    staffed = (created.dt.dayofweek < 5) & ~holidays & created.dt.hour.between(8, 17)
    assert result.loc["weekday_staffed", "tickets"] == staffed.sum()


@pytest.mark.db
def test_misrouting_counts_match_pandas(db_conn, resolved):
    result = run_query(db_conn, query("05_misrouting_cost", "misrouted_vs_correct")).set_index("misrouted")
    owning_team = resolved["subcategory"].map(lambda s: config.SUBCATEGORIES[s].team)
    assert result.loc[True, "resolved"] == (resolved["assigned_team"] != owning_team).sum()


@pytest.mark.db
def test_median_resolution_matches_pandas(db_conn, resolved):
    result = run_query(db_conn, query("06_resolution_times", "by_subcategory")).set_index("subcategory")
    # Compare with the unrounded pandas median: PostgreSQL rounds halves away
    # from zero (16.25 -> 16.3) while NumPy rounds halves to even (16.2), so
    # rounding both sides can differ by a full 0.1.
    expected = resolved.groupby("subcategory")["resolution_hours"].median()
    assert result["median_hours"].astype(float).to_dict() == pytest.approx(expected.to_dict(), abs=0.05 + 1e-9)


@pytest.mark.db
def test_score_distribution_counts_every_response(db_conn, tickets):
    result = run_query(db_conn, query("07_satisfaction", "score_distribution"))
    assert result["responses"].sum() == tickets["satisfaction_score"].notna().sum()
    assert list(result["satisfaction_score"]) == [1, 2, 3, 4, 5]


@pytest.mark.db
def test_spike_detection_finds_every_major_incident(db_conn):
    """The query never sees which tickets belong to an incident."""
    spikes = run_query(db_conn, query("08_recurring_issue_spikes", "daily_spikes"))
    found = set(zip(spikes["day"], spikes["subcategory"]))
    for incident in config.MAJOR_INCIDENTS:
        assert (incident.start.date(), incident.subcategory) in found


@pytest.mark.db
def test_drift_query_shows_the_desktop_support_staffing_cut(db_conn):
    result = run_query(db_conn, query("09_team_drift", "quarterly_by_team"))
    row = result[(result["team"] == "Desktop Support") & (result["quarter"] == pd.Timestamp("2025-04-01").date())]
    assert float(row["change_vs_year_before_pts"].iloc[0]) > 5
