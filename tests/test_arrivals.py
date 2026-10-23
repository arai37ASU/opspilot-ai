"""Tests for arrival times and creation-time attributes.

Exact checks cover rules that must always hold. Pattern checks use loose
bounds so they confirm the intended direction of an effect without failing
on ordinary sampling noise.
"""

import numpy as np
import pandas as pd
import pytest

from opspilot.data_generation import config
from opspilot.data_generation.arrivals import generate_creation_data, sample_rows


@pytest.fixture(scope="module")
def tickets():
    return generate_creation_data(np.random.default_rng(config.DEFAULT_SEED))


def test_same_seed_gives_identical_data(tickets):
    again = generate_creation_data(np.random.default_rng(config.DEFAULT_SEED))
    pd.testing.assert_frame_equal(tickets, again)


def test_different_seed_gives_different_data(tickets):
    other = generate_creation_data(np.random.default_rng(config.DEFAULT_SEED + 1))
    assert not tickets["created_at"].equals(other["created_at"])


def test_sample_rows_never_picks_zero_probability_options():
    rng = np.random.default_rng(0)
    probabilities = np.tile([0.0, 0.7, 0.0, 0.3, 0.0], (20_000, 1))
    chosen = sample_rows(probabilities, rng)
    assert set(chosen) == {1, 3}
    assert abs((chosen == 1).mean() - 0.7) < 0.02


# --- Rules that must always hold ---------------------------------------------


def test_ticket_ids_are_unique_and_follow_creation_order(tickets):
    assert tickets["ticket_id"].is_unique
    assert tickets["created_at"].is_monotonic_increasing
    assert tickets["ticket_id"].iloc[0] == "TKT-000001"


def test_creation_times_fall_inside_the_date_range(tickets):
    assert tickets["created_at"].min() >= pd.Timestamp(config.START_DATE)
    assert tickets["created_at"].max() < pd.Timestamp(config.END_DATE) + pd.Timedelta(days=1)


def test_no_missing_values_outside_major_incident_id(tickets):
    assert not tickets.drop(columns="major_incident_id").isna().any().any()


def test_subcategory_fields_are_consistent(tickets):
    for row in tickets.drop_duplicates("subcategory").itertuples():
        sub = config.SUBCATEGORIES[row.subcategory]
        assert row.category == sub.category
        assert row.ticket_type == sub.ticket_type


def test_service_requests_are_never_p1(tickets):
    requests = tickets[tickets["ticket_type"] == "service_request"]
    assert not (requests["priority"] == "P1").any()


def test_sla_matches_policy(tickets):
    expected = [config.SLA_HOURS[key] for key in zip(tickets["ticket_type"], tickets["priority"])]
    assert (tickets["sla_hours"] == expected).all()
    due = tickets["created_at"] + pd.to_timedelta(tickets["sla_hours"], unit="h")
    assert (tickets["sla_due_at"] == due).all()


def test_students_only_come_from_academic_units(tickets):
    student_departments = set(tickets.loc[tickets["requester_type"] == "student", "department"])
    allowed = {d for d, w in zip(config.DEPARTMENTS, config.DEPARTMENT_WEIGHTS["student"]) if w > 0}
    assert student_departments <= allowed


def test_major_incident_tickets_match_their_incident(tickets):
    in_incident = tickets[tickets["major_incident_id"].notna()]
    for incident_id, incident in enumerate(config.MAJOR_INCIDENTS):
        rows = in_incident[in_incident["major_incident_id"] == incident_id]
        assert len(rows) == incident.ticket_count
        assert (rows["subcategory"] == incident.subcategory).all()
        assert rows["created_at"].min() >= pd.Timestamp(incident.start)


# --- Intended patterns (loose bounds) ------------------------------------------


def test_total_volume_is_close_to_target(tickets):
    burst_total = sum(incident.ticket_count for incident in config.MAJOR_INCIDENTS)
    regular = len(tickets) - burst_total
    assert abs(regular - config.TARGET_TICKET_COUNT) < 0.03 * config.TARGET_TICKET_COUNT


def test_weekdays_are_much_busier_than_weekends(tickets):
    per_day = tickets.groupby(tickets["created_at"].dt.date).size()
    is_weekend = pd.to_datetime(per_day.index).dayofweek >= 5
    assert per_day[~is_weekend].mean() > 3 * per_day[is_weekend].mean()


def test_most_tickets_arrive_during_working_hours(tickets):
    hour = tickets["created_at"].dt.hour
    assert hour.between(8, 17).mean() > 0.75


def test_semester_start_is_busier_than_summer(tickets):
    def mean_daily_volume(period_name):
        days = [
            day for period in config.CALENDAR_PERIODS if period.name == period_name
            for day in pd.date_range(period.start, period.end).date
        ]
        per_day = tickets.groupby(tickets["created_at"].dt.date).size()
        return per_day.reindex(days, fill_value=0).mean()

    assert mean_daily_volume("semester_start") > 1.8 * mean_daily_volume("summer")


def test_faculty_submit_most_classroom_tickets(tickets):
    classroom = tickets[tickets["category"] == "Classroom & AV"]
    assert (classroom["requester_type"] == "faculty").mean() > 0.6


def test_phone_tickets_are_more_urgent_than_portal_tickets(tickets):
    urgent = tickets["priority"].isin(["P1", "P2"])
    assert urgent[tickets["channel"] == "phone"].mean() > urgent[tickets["channel"] == "portal"].mean() + 0.05


def test_misrouting_rate_is_close_to_configured_rate(tickets):
    correct_team = tickets["subcategory"].map(lambda s: config.SUBCATEGORIES[s].team)
    misrouted = (tickets["assigned_team"] != correct_team).mean()
    assert abs(misrouted - config.MISROUTE_RATE) < 0.01
