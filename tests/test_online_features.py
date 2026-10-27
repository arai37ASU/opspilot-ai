"""Training/serving parity for the model's features.

The model was trained on the ticket_features view. At prediction time the API
computes features for one ticket with sql/features/new_ticket_features.sql.
These tests require the two to agree exactly, and the serving query to use
only information available at the ticket's creation time.
"""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from opspilot.analysis.data import read_sql
from opspilot.modeling import config
from opspilot.modeling.dataset import feature_matrix
from opspilot.modeling.online_features import InvalidTicket, TicketAtCreation, features_for
from opspilot.modeling.pipelines import xgboost

pytestmark = pytest.mark.db


def stored_ticket(row) -> TicketAtCreation:
    return TicketAtCreation(
        created_at=row.created_at.to_pydatetime(), priority=row.priority, subcategory=row.subcategory,
        assigned_team=row.assigned_team, requester_type=row.requester_type, channel=row.channel,
        ticket_id=row.ticket_id,
    )


@pytest.fixture(scope="module")
def view(db_conn):
    return read_sql(db_conn, "SELECT * FROM ticket_features WHERE team_open_at_arrival IS NOT NULL "
                             "ORDER BY created_at, ticket_id")


@pytest.fixture(scope="module")
def sample(db_conn, view):
    """Random tickets plus the rare cases where ordering rules matter: tickets
    sharing a creation second, and tickets created at the exact second another
    ticket of the same team was resolved. A planted bug in the second rule
    changed only 1 ticket in a random sample of 800, so these are included on
    purpose rather than left to chance."""
    tied = view[view["created_at"].duplicated(keep=False)]
    resolved_at_arrival = set(row[0] for row in db_conn.execute(
        "SELECT t.ticket_id FROM tickets AS t JOIN tickets AS o "
        "ON o.assigned_team = t.assigned_team AND o.resolved_at = t.created_at AND o.ticket_id <> t.ticket_id"))
    edge_cases = view[view["ticket_id"].isin(resolved_at_arrival)]
    random = view.sample(800, random_state=0)
    return pd.concat([tied, edge_cases, random]).drop_duplicates("ticket_id").reset_index(drop=True)


@pytest.fixture(scope="module")
def online(db_conn, sample):
    return pd.concat([features_for(db_conn, stored_ticket(row)) for row in sample.itertuples()],
                     ignore_index=True)


def test_sample_includes_the_rare_ordering_cases(db_conn, sample):
    assert sample["created_at"].duplicated(keep=False).sum() >= 10
    resolved_at_arrival = db_conn.execute(
        "SELECT count(DISTINCT t.ticket_id) FROM tickets AS t JOIN tickets AS o "
        "ON o.assigned_team = t.assigned_team AND o.resolved_at = t.created_at AND o.ticket_id <> t.ticket_id "
        "WHERE t.ticket_id = ANY(%s)", [list(sample["ticket_id"])]).fetchone()[0]
    assert resolved_at_arrival >= 1


def test_online_features_equal_the_view_exactly(online, sample):
    pd.testing.assert_frame_equal(online, feature_matrix(sample[config.FEATURES]).reset_index(drop=True))


def test_model_scores_are_identical_online_and_offline(db_conn, online, sample, view):
    train = view[view["sla_breached"].notna()].head(8000)
    model = xgboost(n_estimators=30).fit(feature_matrix(train[config.FEATURES]),
                                         train["sla_breached"].astype(bool).astype(int))
    offline_scores = model.predict_proba(feature_matrix(sample[config.FEATURES]))[:, 1]
    assert np.array_equal(model.predict_proba(online)[:, 1], offline_scores)


def test_online_features_ignore_later_data(db_conn, view):
    """Rewind the database to a ticket's creation time; its features must not change."""
    row = next(view[view["created_at"] > pd.Timestamp("2025-05-01")].itertuples())
    before = features_for(db_conn, stored_ticket(row))
    with db_conn.transaction(force_rollback=True):
        db_conn.execute("DELETE FROM tickets WHERE created_at > %s", [row.created_at])
        db_conn.execute(
            "UPDATE tickets SET status = 'in_progress', resolved_at = NULL, resolution_hours = NULL, "
            "resolved_by_team = NULL, sla_breached = NULL, satisfaction_score = NULL, reopened = false "
            "WHERE resolved_at > %s", [row.created_at])
        after = features_for(db_conn, stored_ticket(row))
    pd.testing.assert_frame_equal(before, after)


def test_a_new_ticket_counts_everything_already_in_the_queue(db_conn, view):
    """A new ticket arrives after every stored ticket with the same timestamp."""
    tied = view[view["created_at"].duplicated(keep=False)]
    first = tied.sort_values(["created_at", "ticket_id"]).iloc[0]
    stored = features_for(db_conn, stored_ticket(first))
    new = features_for(db_conn, TicketAtCreation(**{**stored_ticket(first).__dict__, "ticket_id": None}))
    assert new["team_open_per_agent"].iloc[0] >= stored["team_open_per_agent"].iloc[0]


def valid_ticket(**changes) -> TicketAtCreation:
    fields = dict(created_at=datetime(2025, 3, 12, 19, 30), priority="P2", subcategory="wifi_connectivity",
                  assigned_team="Network Operations", requester_type="student", channel="portal")
    return TicketAtCreation(**{**fields, **changes})


def test_a_valid_new_ticket_gets_a_complete_feature_row(db_conn):
    row = features_for(db_conn, valid_ticket())
    assert list(row.columns) == config.FEATURES
    assert len(row) == 1
    assert row["hours_until_staffed"].iloc[0] == pytest.approx(12.5)  # Wednesday 19:30 -> Thursday 08:00
    assert row["sla_hours"].iloc[0] == 8.0


@pytest.mark.parametrize("changes, message", [
    ({"subcategory": "teleportation"}, "unknown subcategory"),
    ({"assigned_team": "Facilities"}, "unknown team"),
    ({"subcategory": "password_reset", "priority": "P1"}, "no SLA policy"),
    ({"created_at": datetime(2031, 1, 1, 9, 0)}, "outside the calendar"),
])
def test_tickets_that_cannot_be_scored_are_rejected(db_conn, changes, message):
    with pytest.raises(InvalidTicket, match=message):
        features_for(db_conn, valid_ticket(**changes))
