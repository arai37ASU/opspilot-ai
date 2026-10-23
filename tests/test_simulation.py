"""Tests for the resolution simulation.

Breaches are computed here as resolution_hours > sla_hours because the
official sla_breached column (with snapshot censoring) is added later in
generate.py.
"""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from opspilot.data_generation import config
from opspilot.data_generation.arrivals import generate_creation_data
from opspilot.data_generation.simulation import next_staffed_time, queue_wait_hours, simulate_resolution


@pytest.fixture(scope="module")
def tickets():
    rng = np.random.default_rng(config.DEFAULT_SEED)
    tickets = simulate_resolution(generate_creation_data(rng), rng)
    tickets["breached"] = tickets["resolution_hours"] > tickets["sla_hours"]
    return tickets


# --- Staffing and queue helpers ----------------------------------------------------


@pytest.mark.parametrize(
    "moment, expected",
    [
        (datetime(2024, 3, 12, 7, 30), datetime(2024, 3, 12, 8, 0)),    # Tuesday before opening
        (datetime(2024, 3, 12, 9, 15), datetime(2024, 3, 12, 9, 15)),   # Tuesday during hours
        (datetime(2024, 3, 15, 19, 0), datetime(2024, 3, 16, 10, 0)),   # Friday evening -> Saturday
        (datetime(2024, 3, 16, 17, 0), datetime(2024, 3, 17, 10, 0)),   # Saturday after closing
        (datetime(2024, 7, 4, 9, 0), datetime(2024, 7, 4, 10, 0)),      # holiday uses weekend hours
    ],
)
def test_next_staffed_time(moment, expected):
    assert next_staffed_time(moment) == expected


def test_queue_wait_grows_with_load_but_stays_capped():
    waits = [queue_wait_hours(backlog, agents=3) for backlog in range(0, 200, 10)]
    assert waits[0] == 0
    assert waits == sorted(waits)
    assert waits[-1] < config.MAX_QUEUE_WAIT_HOURS
    assert queue_wait_hours(int(config.QUEUE_HALF_LOAD * 3), agents=3) == pytest.approx(config.MAX_QUEUE_WAIT_HOURS / 2)


def test_unsorted_input_is_rejected():
    rng = np.random.default_rng(0)
    shuffled = generate_creation_data(rng).sample(frac=1, random_state=0)
    with pytest.raises(ValueError):
        simulate_resolution(shuffled, rng)


# --- Rules that must always hold ---------------------------------------------


def test_simulation_is_reproducible(tickets):
    rng = np.random.default_rng(config.DEFAULT_SEED)
    again = simulate_resolution(generate_creation_data(rng), rng)
    pd.testing.assert_series_equal(again["resolved_at"], tickets["resolved_at"])


def test_resolution_happens_after_creation(tickets):
    assert (tickets["resolved_at"] > tickets["created_at"]).all()
    assert (tickets["resolution_hours"] > 0).all()
    hours = (tickets["resolved_at"] - tickets["created_at"]) / pd.Timedelta(hours=1)
    assert np.allclose(tickets["resolution_hours"], hours, atol=0.01)


def test_tickets_are_resolved_by_the_owning_team(tickets):
    owner = tickets["subcategory"].map(lambda s: config.SUBCATEGORIES[s].team)
    assert (tickets["resolved_by_team"] == owner).all()


def test_misrouted_tickets_are_always_reassigned(tickets):
    misrouted = tickets["assigned_team"] != tickets["resolved_by_team"]
    assert (tickets.loc[misrouted, "reassignment_count"] >= 1).all()
    assert tickets["reassignment_count"].between(0, 3).all()


def test_input_columns_are_unchanged():
    rng = np.random.default_rng(config.DEFAULT_SEED)
    created = generate_creation_data(rng)
    result = simulate_resolution(created, rng)
    pd.testing.assert_frame_equal(result[created.columns], created)


# --- Intended patterns (loose bounds) ------------------------------------------


def test_overall_breach_rate_is_plausible(tickets):
    assert 0.05 < tickets["breached"].mean() < 0.30


def test_no_priority_decides_the_outcome(tickets):
    by_priority = tickets.groupby("priority")["breached"].mean()
    assert by_priority.between(0.005, 0.8).all()


def test_reopen_rate_is_plausible(tickets):
    assert 0.04 < tickets["reopened"].mean() < 0.10


def test_reopened_tickets_take_longer(tickets):
    medians = tickets.groupby("reopened")["resolution_hours"].median()
    assert medians[True] > 1.5 * medians[False]


def test_misrouted_tickets_breach_more(tickets):
    misrouted = tickets["assigned_team"] != tickets["resolved_by_team"]
    assert tickets.loc[misrouted, "breached"].mean() > tickets.loc[~misrouted, "breached"].mean()


def test_after_hours_tickets_breach_more(tickets):
    created = tickets["created_at"]
    business_hours = (created.dt.dayofweek < 5) & created.dt.hour.between(8, 17)
    assert tickets.loc[~business_hours, "breached"].mean() > 1.5 * tickets.loc[business_hours, "breached"].mean()


def test_desktop_support_staffing_cut_raises_breaches(tickets):
    desktop = tickets[tickets["resolved_by_team"] == "Desktop Support"]
    months = desktop["created_at"].dt.month.between(4, 6)
    years = desktop["created_at"].dt.year
    before = desktop.loc[months & (years == 2024), "breached"].mean()
    during = desktop.loc[months & (years == 2025), "breached"].mean()
    assert during > before
