"""Consistency checks for the generator configuration.

A typo in config.py (a weight list that does not sum to 1, a team name that
does not exist) would silently distort the dataset, so it is cheaper to catch
it here than in the generated data.
"""

import math

import pytest

from opspilot.data_generation import config


def assert_is_distribution(weights, expected_length):
    assert len(weights) == expected_length
    assert all(w >= 0 for w in weights)
    assert math.isclose(sum(weights), 1.0, abs_tol=1e-9)


def test_requester_type_weights():
    assert_is_distribution(config.REQUESTER_TYPE_WEIGHTS, len(config.REQUESTER_TYPES))


@pytest.mark.parametrize("requester_type", config.REQUESTER_TYPES)
def test_weights_per_requester_type(requester_type):
    assert_is_distribution(config.DEPARTMENT_WEIGHTS[requester_type], len(config.DEPARTMENTS))
    assert_is_distribution(config.CATEGORY_WEIGHTS[requester_type], len(config.CATEGORIES))
    assert_is_distribution(config.CHANNEL_WEIGHTS[requester_type], len(config.CHANNELS))


def test_subcategories_reference_known_values():
    for name, sub in config.SUBCATEGORIES.items():
        assert sub.category in config.CATEGORIES, name
        assert sub.ticket_type in config.TICKET_TYPES, name
        assert sub.team in config.TEAM_AGENTS, name
        assert sub.weight > 0, name
        assert sub.median_work_hours > 0, name
        assert_is_distribution(sub.priority_weights, len(config.PRIORITIES))


def test_every_category_has_subcategories():
    used = {sub.category for sub in config.SUBCATEGORIES.values()}
    assert used == set(config.CATEGORIES)


def test_service_requests_are_never_p1():
    for name, sub in config.SUBCATEGORIES.items():
        if sub.ticket_type == "service_request":
            assert sub.priority_weights[0] == 0, name


def test_sla_policy_covers_every_possible_combination():
    for sub in config.SUBCATEGORIES.values():
        for priority, weight in zip(config.PRIORITIES, sub.priority_weights):
            if weight > 0:
                assert (sub.ticket_type, priority) in config.SLA_HOURS


def test_higher_priority_has_shorter_sla():
    for ticket_type in config.TICKET_TYPES:
        hours = [config.SLA_HOURS[(ticket_type, p)] for p in config.PRIORITIES
                 if (ticket_type, p) in config.SLA_HOURS]
        assert hours == sorted(hours)


def test_calendar_periods_are_ordered_and_do_not_overlap():
    periods = config.CALENDAR_PERIODS
    for period in periods:
        assert period.start <= period.end
        assert config.START_DATE <= period.start and period.end <= config.END_DATE
        assert set(period.category_multipliers) <= set(config.CATEGORIES)
    for earlier, later in zip(periods, periods[1:]):
        assert earlier.end < later.start


def test_time_weights_have_expected_shape():
    assert len(config.HOUR_WEIGHTS) == 24
    assert len(config.WEEKDAY_WEIGHTS) == 7


def test_staffing_changes_and_incidents_reference_known_values():
    for change in config.STAFFING_CHANGES:
        assert change.team in config.TEAM_AGENTS
        assert 0 < change.agents
    for incident in config.MAJOR_INCIDENTS:
        assert incident.subcategory in config.SUBCATEGORIES
        assert config.START_DATE <= incident.start.date() <= config.END_DATE
