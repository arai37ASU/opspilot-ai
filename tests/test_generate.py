"""End-to-end tests for the assembled dataset and its CSV output."""

import pandas as pd
import pytest

from opspilot.data_generation import config
from opspilot.data_generation.generate import (
    SNAPSHOT_TIME,
    TICKET_COLUMNS,
    build_calendar_days,
    build_sla_policies,
    build_subcategories,
    build_teams,
    build_tickets,
    main,
)

OUTCOME_COLUMNS = ["resolved_at", "resolution_hours", "resolved_by_team", "sla_breached"]


@pytest.fixture(scope="module")
def tickets():
    return build_tickets(config.DEFAULT_SEED)


def test_columns_match_the_documented_schema(tickets):
    assert list(tickets.columns) == TICKET_COLUMNS


def test_status_values_are_allowed(tickets):
    assert set(tickets["status"]) <= set(config.STATUSES)


def test_outcomes_exist_only_for_resolved_tickets(tickets):
    resolved = tickets["status"] == "resolved"
    assert tickets.loc[resolved, OUTCOME_COLUMNS].notna().all().all()
    assert tickets.loc[~resolved, OUTCOME_COLUMNS].isna().all().all()
    assert not tickets.loc[~resolved, "reopened"].any()
    assert tickets.loc[~resolved, "satisfaction_score"].isna().all()


def test_nothing_is_resolved_after_the_snapshot(tickets):
    assert (tickets["resolved_at"].dropna() <= SNAPSHOT_TIME).all()


def test_sla_breached_matches_its_definition(tickets):
    resolved = tickets[tickets["status"] == "resolved"]
    expected = resolved["resolution_hours"] > resolved["sla_hours"]
    assert (resolved["sla_breached"] == expected).all()


def test_unresolved_tickets_are_near_the_end_of_the_data(tickets):
    unresolved = tickets[tickets["status"].isin(["open", "in_progress"])]
    assert len(unresolved) > 0
    assert (unresolved["created_at"] > SNAPSHOT_TIME - pd.Timedelta(days=45)).all()


def test_cancellation_rate_is_close_to_configured_rate(tickets):
    share = (tickets["status"] == "cancelled").mean()
    assert abs(share - config.CANCEL_RATE) < 0.005


def test_satisfaction_scores_are_valid_and_partial(tickets):
    scores = tickets["satisfaction_score"].dropna()
    assert scores.between(1, 5).all()
    response_rate = len(scores) / (tickets["status"] == "resolved").sum()
    assert 0.2 < response_rate < 0.4


def test_breached_tickets_get_lower_satisfaction(tickets):
    surveyed = tickets.dropna(subset=["satisfaction_score"])
    by_breach = surveyed.groupby("sla_breached")["satisfaction_score"].mean()
    assert by_breach[True] < by_breach[False] - 0.5


def test_overall_breach_rate_is_in_the_target_band(tickets):
    assert 0.12 < tickets["sla_breached"].mean() < 0.20


def test_reference_tables_match_config():
    teams = build_teams()
    assert dict(zip(teams["team"], teams["agents"])) == config.TEAM_AGENTS
    policies = build_sla_policies()
    assert len(policies) == len(config.SLA_HOURS)
    subcategories = build_subcategories()
    assert list(subcategories["subcategory"]) == list(config.SUBCATEGORIES)
    assert "median_work_hours" not in subcategories.columns


def test_calendar_covers_every_day_once():
    calendar = build_calendar_days()
    expected_days = (config.END_DATE - config.START_DATE).days + 1
    assert len(calendar) == expected_days
    assert calendar["day"].is_unique
    assert calendar["is_holiday"].sum() == len(config.HOLIDAYS)
    assert calendar.loc[calendar["is_weekend"], "day_of_week"].isin([6, 7]).all()
    semester_days = sum((p.end - p.start).days + 1 for p in config.CALENDAR_PERIODS if p.name == "semester_start")
    assert (calendar["academic_period"] == "semester_start").sum() == semester_days


def test_main_writes_readable_csv_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["generate", "--output-dir", str(tmp_path)])
    main()

    written = pd.read_csv(tmp_path / "tickets.csv", parse_dates=["created_at", "resolved_at", "sla_due_at"])
    assert list(written.columns) == TICKET_COLUMNS
    assert len(written) == len(build_tickets(config.DEFAULT_SEED))
    for name in ["teams", "sla_policies", "subcategories", "calendar_days"]:
        assert (tmp_path / f"{name}.csv").exists()
    assert "breach rate" in capsys.readouterr().out
