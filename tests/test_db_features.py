"""Tests for the ticket_features view.

The most important test is the time-travel test: features must come out the
same whether they are computed from the full data or from the database as it
looked at an earlier cutoff. Any feature that used future information would
change.
"""

import pandas as pd
import pytest

from opspilot.data_generation.simulation import next_staffed_time
from pandas_reference import arrivals_in_previous, open_at_arrival

pytestmark = pytest.mark.db

POST_CREATION_COLUMNS = {
    "status", "resolved_at", "resolution_hours", "resolved_by_team",
    "reassignment_count", "reopened", "satisfaction_score",
}


def read_features(conn) -> pd.DataFrame:
    cursor = conn.execute("SELECT * FROM ticket_features ORDER BY ticket_id")
    return pd.DataFrame(cursor.fetchall(), columns=[column.name for column in cursor.description])


@pytest.fixture(scope="module")
def features(db_conn):
    return read_features(db_conn)


@pytest.fixture(scope="module")
def tickets(data_dir):
    return pd.read_csv(data_dir / "tickets.csv", parse_dates=["created_at", "resolved_at"])


def test_one_row_per_ticket(features, tickets):
    assert len(features) == len(tickets)
    assert features["ticket_id"].is_unique


def test_no_post_creation_columns(features):
    assert not POST_CREATION_COLUMNS & set(features.columns)


def test_label_is_present_only_for_resolved_tickets(features, tickets):
    resolved_ids = set(tickets.loc[tickets["status"] == "resolved", "ticket_id"])
    labelled_ids = set(features.loc[features["sla_breached"].notna(), "ticket_id"])
    assert labelled_ids == resolved_ids


def test_features_do_not_change_when_future_data_is_removed(db_conn, features):
    """Rewind the database to a cutoff and rebuild the view.

    Tickets created after the cutoff are deleted and resolutions after the
    cutoff are undone, which is what the database would have held at that
    moment. Features for earlier tickets must be identical.
    """
    cutoff = "2025-03-01"
    with db_conn.transaction(force_rollback=True):
        db_conn.execute("DELETE FROM tickets WHERE created_at >= %s", [cutoff])
        db_conn.execute(
            "UPDATE tickets SET status = 'in_progress', resolved_at = NULL, resolution_hours = NULL, "
            "resolved_by_team = NULL, sla_breached = NULL, satisfaction_score = NULL, reopened = false "
            "WHERE resolved_at >= %s",
            [cutoff],
        )
        db_conn.execute("REFRESH MATERIALIZED VIEW ticket_features")
        rewound = read_features(db_conn)

    before_cutoff = features[features["created_at"] < pd.Timestamp(cutoff)].reset_index(drop=True)
    # The label legitimately changes: some outcomes were not known yet.
    pd.testing.assert_frame_equal(
        rewound.drop(columns="sla_breached"),
        before_cutoff.drop(columns="sla_breached"),
    )


def test_backlog_matches_independent_pandas_calculation(features, tickets):
    expected = open_at_arrival(tickets)
    actual = features.set_index("ticket_id")["team_open_at_arrival"].dropna().astype(int)
    pd.testing.assert_series_equal(actual.sort_index(), expected.sort_index(), check_names=False)


@pytest.mark.parametrize(
    "column, group_column, window",
    [
        ("team_arrivals_prev_24h", "assigned_team", pd.Timedelta(hours=24)),
        ("subcategory_arrivals_prev_2h", "subcategory", pd.Timedelta(hours=2)),
        ("subcategory_arrivals_prev_24h", "subcategory", pd.Timedelta(hours=24)),
    ],
)
def test_recent_arrival_counts_match_pandas(features, tickets, column, group_column, window):
    expected = arrivals_in_previous(tickets, group_column, window)
    actual = features.set_index("ticket_id")[column]
    assert (actual.sort_index() == expected.sort_index()).all()


def test_hours_until_staffed_matches_the_simulation_rule(features):
    """Same published hours, implemented independently in simulation.py."""
    sample = features.sample(2000, random_state=0)
    expected = [
        (pd.Timestamp(next_staffed_time(created.to_pydatetime())) - created) / pd.Timedelta(hours=1)
        for created in sample["created_at"]
    ]
    # The view rounds to two decimals, so allow half a hundredth (plus float noise).
    assert sample["hours_until_staffed"].astype(float).to_numpy() == pytest.approx(expected, abs=0.005 + 1e-9)


def test_team_breach_history_uses_only_earlier_resolutions(features, tickets):
    """Recompute the 30-day team breach rate for a sample of tickets by hand."""
    labelled = tickets[tickets["sla_breached"].notna()]
    sample = features.dropna(subset=["team_breach_rate_prev_30d"]).sample(200, random_state=0)
    for row in sample.itertuples():
        window = labelled[
            (labelled["assigned_team"] == row.assigned_team)
            & (labelled["resolved_at"] < row.created_at)
            & (labelled["resolved_at"] >= row.created_at - pd.Timedelta(days=30))
        ]
        assert row.team_resolved_prev_30d == len(window)
        assert float(row.team_breach_rate_prev_30d) == pytest.approx(window["sla_breached"].astype(bool).mean(), abs=5e-5)


def test_history_is_missing_only_at_the_start(features):
    missing = features[features["team_breach_rate_prev_30d"].isna()]
    assert (missing["created_at"] < pd.Timestamp("2024-02-01")).all()
