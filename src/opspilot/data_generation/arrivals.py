"""Arrival times and creation-time attributes for synthetic tickets.

Everything produced here is known at the moment a ticket is submitted.
Outcome fields (resolution, reopening, satisfaction) are added later by the
simulation, so nothing in this module can leak them.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from opspilot.data_generation import config

SUBCATEGORY_NAMES = list(config.SUBCATEGORIES)
TEAM_NAMES = list(config.TEAM_AGENTS)


def sample_rows(probabilities: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Draw one column index per row of a probability matrix.

    This is the vectorised version of calling rng.choice once per row with a
    different p each time. Rows do not need to be normalised.
    """
    probabilities = probabilities / probabilities.sum(axis=1, keepdims=True)
    cumulative = probabilities.cumsum(axis=1)
    draws = rng.random((len(probabilities), 1))
    chosen = (cumulative <= draws).sum(axis=1)
    # Floating-point rounding can leave the last cumulative value just below 1.
    return np.minimum(chosen, probabilities.shape[1] - 1)


def sample_by_key(keys: pd.Series, weights_by_key: dict, options: list, rng: np.random.Generator) -> np.ndarray:
    """Sample one option per row, using the weight list that belongs to that row's key."""
    probabilities = np.array([weights_by_key[key] for key in keys], dtype=float)
    return np.array(options, dtype=object)[sample_rows(probabilities, rng)]


def period_on(day: date) -> config.CalendarPeriod | None:
    for period in config.CALENDAR_PERIODS:
        if period.start <= day <= period.end:
            return period
    return None


def day_volume_multiplier(day: date) -> float:
    multiplier = config.WEEKDAY_WEIGHTS[day.weekday()]
    if day in config.HOLIDAYS:
        multiplier *= config.HOLIDAY_VOLUME_MULTIPLIER
    period = period_on(day)
    if period is not None:
        multiplier *= period.volume_multiplier
    return multiplier


def hourly_expected_volume() -> pd.DataFrame:
    """Expected number of tickets for every hour in the date range.

    The weights only describe the shape of demand; they are scaled so the
    expected total equals TARGET_TICKET_COUNT.
    """
    hours = pd.date_range(
        pd.Timestamp(config.START_DATE),
        pd.Timestamp(config.END_DATE + timedelta(days=1)),
        freq="h",
        inclusive="left",
    )
    day_weights = {day: day_volume_multiplier(day) for day in set(hours.date)}
    weights = np.array(config.HOUR_WEIGHTS)[hours.hour] * np.array([day_weights[day] for day in hours.date])
    expected = weights * config.TARGET_TICKET_COUNT / weights.sum()
    return pd.DataFrame({"hour_start": hours, "expected_tickets": expected})


def generate_arrival_times(rng: np.random.Generator) -> pd.DataFrame:
    """Ticket creation times from a Poisson process, plus major-incident bursts.

    Returns one row per ticket with `created_at` and `major_incident_id`
    (index into config.MAJOR_INCIDENTS, missing for regular tickets).
    """
    hourly = hourly_expected_volume()
    counts = rng.poisson(hourly["expected_tickets"].to_numpy())
    hour_starts = np.repeat(hourly["hour_start"].to_numpy(), counts)
    offsets = rng.integers(0, 3600, size=len(hour_starts)).astype("timedelta64[s]")
    frames = [pd.DataFrame({"created_at": hour_starts + offsets, "major_incident_id": np.nan})]

    for incident_id, incident in enumerate(config.MAJOR_INCIDENTS):
        seconds = rng.integers(0, int(incident.duration_hours * 3600), size=incident.ticket_count)
        frames.append(pd.DataFrame({
            "created_at": pd.Timestamp(incident.start) + pd.to_timedelta(seconds, unit="s"),
            "major_incident_id": incident_id,
        }))

    arrivals = pd.concat(frames, ignore_index=True)
    arrivals["major_incident_id"] = arrivals["major_incident_id"].astype("Int64")
    return arrivals.sort_values("created_at", kind="stable", ignore_index=True)


def sample_categories(tickets: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    base = np.array([config.CATEGORY_WEIGHTS[r] for r in tickets["requester_type"]], dtype=float)

    seasonal_by_day = {}
    for day in set(tickets["created_at"].dt.date):
        period = period_on(day)
        overrides = period.category_multipliers if period else {}
        seasonal_by_day[day] = [overrides.get(category, 1.0) for category in config.CATEGORIES]
    seasonal = np.array([seasonal_by_day[day] for day in tickets["created_at"].dt.date])

    return np.array(config.CATEGORIES, dtype=object)[sample_rows(base * seasonal, rng)]


def sample_subcategories(categories: pd.Series, rng: np.random.Generator) -> np.ndarray:
    # One weight row per category, with zeros for subcategories of other categories.
    weights_by_category = {
        category: [sub.weight if sub.category == category else 0.0 for sub in config.SUBCATEGORIES.values()]
        for category in config.CATEGORIES
    }
    return sample_by_key(categories, weights_by_category, SUBCATEGORY_NAMES, rng)


def sample_priorities(tickets: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    weights = np.array([config.SUBCATEGORIES[s].priority_weights for s in tickets["subcategory"]], dtype=float)
    boost = tickets["channel"].map(config.CHANNEL_URGENCY_BOOST).fillna(1.0).to_numpy(dtype=float)
    weights[:, :2] *= boost[:, None]  # P1 and P2 columns
    return np.array(config.PRIORITIES, dtype=object)[sample_rows(weights, rng)]


def route_tickets(subcategories: pd.Series, rng: np.random.Generator) -> np.ndarray:
    """Initial team assignment. A small share is sent to the wrong team."""
    correct = np.array([TEAM_NAMES.index(config.SUBCATEGORIES[s].team) for s in subcategories])
    misrouted = rng.random(len(correct)) < config.MISROUTE_RATE
    # Shifting by 1..(n-1) positions picks uniformly among the other teams.
    shift = rng.integers(1, len(TEAM_NAMES), size=len(correct))
    assigned = np.where(misrouted, (correct + shift) % len(TEAM_NAMES), correct)
    return np.array(TEAM_NAMES, dtype=object)[assigned]


def assign_creation_attributes(arrivals: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Add requester, issue, priority, routing, and SLA fields to arrival times.

    Attributes are sampled in cause-and-effect order: who is asking, then
    what the issue is, then how urgent it is, then where it is routed.
    """
    tickets = arrivals.copy()
    n = len(tickets)

    tickets["requester_type"] = rng.choice(config.REQUESTER_TYPES, size=n, p=config.REQUESTER_TYPE_WEIGHTS)
    tickets["department"] = sample_by_key(tickets["requester_type"], config.DEPARTMENT_WEIGHTS, config.DEPARTMENTS, rng)
    tickets["channel"] = sample_by_key(tickets["requester_type"], config.CHANNEL_WEIGHTS, config.CHANNELS, rng)
    tickets["category"] = sample_categories(tickets, rng)
    tickets["subcategory"] = sample_subcategories(tickets["category"], rng)

    # Major-incident tickets are about the incident, whatever the requester mix suggests.
    in_incident = tickets["major_incident_id"].notna()
    incident_subcategories = tickets.loc[in_incident, "major_incident_id"].map(
        lambda incident_id: config.MAJOR_INCIDENTS[incident_id].subcategory
    )
    tickets.loc[in_incident, "subcategory"] = incident_subcategories
    tickets.loc[in_incident, "category"] = incident_subcategories.map(lambda s: config.SUBCATEGORIES[s].category)

    tickets["ticket_type"] = tickets["subcategory"].map(lambda s: config.SUBCATEGORIES[s].ticket_type)
    tickets["priority"] = sample_priorities(tickets, rng)
    tickets["assigned_team"] = route_tickets(tickets["subcategory"], rng)
    tickets["sla_hours"] = [
        float(config.SLA_HOURS[(ticket_type, priority)])
        for ticket_type, priority in zip(tickets["ticket_type"], tickets["priority"])
    ]
    tickets["sla_due_at"] = tickets["created_at"] + pd.to_timedelta(tickets["sla_hours"], unit="h")
    tickets["ticket_id"] = [f"TKT-{number:06d}" for number in range(1, n + 1)]

    return tickets[[
        "ticket_id", "created_at", "channel", "requester_type", "department",
        "category", "subcategory", "ticket_type", "priority", "assigned_team",
        "sla_hours", "sla_due_at", "major_incident_id",
    ]]


def generate_creation_data(rng: np.random.Generator) -> pd.DataFrame:
    """All tickets with the fields available at submission time."""
    return assign_creation_attributes(generate_arrival_times(rng), rng)
