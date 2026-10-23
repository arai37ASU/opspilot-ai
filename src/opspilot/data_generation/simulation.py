"""Queue simulation that turns creation-time tickets into resolution outcomes.

Tickets are processed in creation order. Each team keeps a heap of the
resolution times of its in-flight tickets, so at every arrival we know how
many tickets that team is already holding. A busier team means a longer queue
wait, which is how workload ends up driving SLA breaches.

This is an approximation, not an agent-by-agent simulation: queue wait is a
smooth function of backlog per agent rather than an explicit work schedule.
That keeps the mechanism small enough to explain while still producing the
relationships described in docs/dataset_design.md.

Times inside the simulation are floats measured in hours since START_DATE,
which keeps the per-ticket loop fast and simple.
"""

import heapq
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from opspilot.data_generation import config

EPOCH = pd.Timestamp(config.START_DATE)


def is_reduced_staffing_day(day: date) -> bool:
    return day.weekday() >= 5 or day in config.HOLIDAYS


def next_staffed_time(moment: datetime) -> datetime:
    """The earliest time at or after `moment` when agents are working."""
    day = moment.date()
    while True:
        start_hour, end_hour = (
            config.WEEKEND_STAFFED_HOURS if is_reduced_staffing_day(day) else config.WEEKDAY_STAFFED_HOURS
        )
        opens = datetime(day.year, day.month, day.day, start_hour)
        closes = datetime(day.year, day.month, day.day, end_hour)
        if moment < closes:
            return max(moment, opens)
        day += timedelta(days=1)


def agents_on(team: str, day: date) -> float:
    agents = config.TEAM_AGENTS[team]
    for change in config.STAFFING_CHANGES:
        if change.team == team and change.start <= day <= change.end:
            agents = change.agents
    if is_reduced_staffing_day(day):
        agents *= config.WEEKEND_CAPACITY_FACTOR
    return agents


def queue_wait_hours(backlog: int, agents: float) -> float:
    """Expected wait before work starts, rising with load but capped.

    At QUEUE_HALF_LOAD tickets per agent the wait is half of the maximum;
    beyond that it flattens out instead of growing without limit.
    """
    load = backlog / agents
    return config.MAX_QUEUE_WAIT_HOURS * load / (load + config.QUEUE_HALF_LOAD)


def lognormal(rng: np.random.Generator, median: np.ndarray | float, sigma: float, size: int) -> np.ndarray:
    # numpy parameterises by the mean of log(x); log(median) is that mean.
    return rng.lognormal(np.log(median), sigma, size)


def simulate_resolution(tickets: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Add resolution outcomes to creation-time tickets.

    Expects tickets sorted by `created_at` (as produced by arrivals.py).
    Adds `resolved_by_team`, `reassignment_count`, `reopened`, `resolved_at`
    and `resolution_hours`. `resolved_at` is the true resolution time and may
    fall after the data snapshot; generate.py applies the snapshot later.
    """
    if not tickets["created_at"].is_monotonic_increasing:
        raise ValueError("tickets must be sorted by created_at")

    n = len(tickets)
    subcategories = [config.SUBCATEGORIES[s] for s in tickets["subcategory"]]
    resolving_team = np.array([sub.team for sub in subcategories], dtype=object)
    priority = tickets["priority"].to_numpy()

    # Everything that does not depend on the queue is drawn up front.
    misrouted = tickets["assigned_team"].to_numpy() != resolving_team
    reassignments = misrouted.astype(int) + rng.binomial(2, config.EXTRA_REASSIGNMENT_RATE, size=n)
    reassignment_delay = np.array([
        lognormal(rng, config.REASSIGNMENT_DELAY_MEDIAN_HOURS, 0.6, count).sum() for count in reassignments
    ])

    typical_work = (
        np.array([sub.median_work_hours for sub in subcategories])
        * pd.Series(priority).map(config.PRIORITY_WORK_MULTIPLIER).to_numpy()
    )
    work = lognormal(rng, typical_work, config.WORK_TIME_SIGMA, n)

    # Rushed fixes come back more often.
    reopen_rate = np.where(work < 0.5 * typical_work, config.REOPEN_FAST_FIX_RATE, config.REOPEN_BASE_RATE)
    reopened = rng.random(n) < reopen_rate
    reopen_extra = np.where(
        reopened,
        lognormal(rng, config.REOPEN_DETECTION_MEDIAN_HOURS, 0.6, n) + work * config.REOPEN_WORK_FRACTION,
        0.0,
    )

    wait_noise = lognormal(rng, 1.0, config.QUEUE_WAIT_SIGMA, n)
    queue_multiplier = pd.Series(priority).map(config.PRIORITY_QUEUE_MULTIPLIER).to_numpy()

    created = tickets["created_at"].dt.to_pydatetime()
    created_hours = ((tickets["created_at"] - EPOCH) / pd.Timedelta(hours=1)).to_numpy()
    in_flight = {team: [] for team in config.TEAM_AGENTS}
    resolved_hours = np.empty(n)

    for i in range(n):
        team = resolving_team[i]
        now = created_hours[i]

        open_tickets = in_flight[team]
        while open_tickets and open_tickets[0] <= now:
            heapq.heappop(open_tickets)
        backlog = len(open_tickets)

        # P1 tickets are picked up by on-call staff immediately.
        if priority[i] == "P1":
            start = now
        else:
            start = (pd.Timestamp(next_staffed_time(created[i])) - EPOCH) / pd.Timedelta(hours=1)

        wait = queue_wait_hours(backlog, agents_on(team, created[i].date())) * queue_multiplier[i] * wait_noise[i]
        resolved_hours[i] = start + wait + reassignment_delay[i] + work[i] + reopen_extra[i]
        heapq.heappush(open_tickets, resolved_hours[i])

    result = tickets.copy()
    result["resolved_by_team"] = resolving_team
    result["reassignment_count"] = reassignments
    result["reopened"] = reopened
    # Round to whole seconds, matching created_at precision.
    result["resolved_at"] = (EPOCH + pd.to_timedelta(resolved_hours, unit="h")).round("s")
    result["resolution_hours"] = ((result["resolved_at"] - result["created_at"]) / pd.Timedelta(hours=1)).round(2)
    return result
