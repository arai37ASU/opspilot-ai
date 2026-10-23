"""Build the synthetic service-desk dataset and write it to CSV.

Usage:
    python -m opspilot.data_generation.generate --seed 42 --output-dir data/raw

The pipeline runs in the same order a real ticket's life does: arrival and
submission details, description, resolution, and finally what an analyst
would see in a snapshot taken at the end of END_DATE.
"""

import argparse
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from opspilot.data_generation import config
from opspilot.data_generation.arrivals import generate_creation_data, period_on
from opspilot.data_generation.descriptions import generate_descriptions
from opspilot.data_generation.simulation import simulate_resolution

SNAPSHOT_TIME = pd.Timestamp(config.END_DATE + timedelta(days=1))

TICKET_COLUMNS = [
    "ticket_id", "created_at", "channel", "requester_type", "department",
    "category", "subcategory", "ticket_type", "priority", "assigned_team",
    "description", "sla_hours", "sla_due_at", "status", "resolved_at",
    "resolution_hours", "resolved_by_team", "reassignment_count", "reopened",
    "satisfaction_score", "sla_breached",
]


def apply_snapshot(tickets: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Hide outcomes that would not be known yet at SNAPSHOT_TIME, and cancel a few tickets.

    Unresolved tickets created in the last day are `open`; older ones are
    `in_progress`. That is a simplification: the simulation does not track
    the moment work starts.
    """
    tickets = tickets.copy()
    cancelled = rng.random(len(tickets)) < config.CANCEL_RATE
    unresolved = ~cancelled & (tickets["resolved_at"] > SNAPSHOT_TIME)
    recent = tickets["created_at"] > SNAPSHOT_TIME - pd.Timedelta(days=1)

    tickets["status"] = "resolved"
    tickets.loc[unresolved, "status"] = np.where(recent[unresolved], "open", "in_progress")
    tickets.loc[cancelled, "status"] = "cancelled"

    not_resolved = tickets["status"] != "resolved"
    tickets.loc[not_resolved, "resolved_at"] = pd.NaT
    tickets.loc[not_resolved, "resolution_hours"] = np.nan
    tickets.loc[not_resolved, "resolved_by_team"] = None
    # A reopen or late reassignment cannot be observed before the ticket is resolved.
    tickets.loc[not_resolved, "reopened"] = False
    tickets.loc[cancelled, "reassignment_count"] = 0

    tickets["sla_breached"] = (tickets["resolution_hours"] > tickets["sla_hours"]).astype("boolean")
    tickets.loc[not_resolved, "sla_breached"] = pd.NA
    return tickets


def add_satisfaction(tickets: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Survey scores for resolved tickets, with realistic non-response."""
    tickets = tickets.copy()
    n = len(tickets)
    resolved = (tickets["status"] == "resolved").to_numpy()
    breached = tickets["sla_breached"].fillna(False).to_numpy(dtype=bool)
    days_open = tickets["resolution_hours"].fillna(0).to_numpy(dtype=float) / 24

    experience = (
        config.SATISFACTION_BASE
        - config.SATISFACTION_BREACH_PENALTY * breached
        - config.SATISFACTION_REOPEN_PENALTY * tickets["reopened"].to_numpy(dtype=bool)
        - config.SATISFACTION_PENALTY_PER_DAY * days_open
        - tickets["category"].map(config.SATISFACTION_CATEGORY_PENALTY).fillna(0).to_numpy(dtype=float)
        + rng.normal(0, config.SATISFACTION_NOISE, n)
    )
    score = np.clip(np.rint(experience), 1, 5).astype(int)

    # People with a very good or very bad experience answer surveys more often.
    extreme = (score <= 2) | (score == 5)
    response_rate = config.SURVEY_BASE_RESPONSE_RATE + config.SURVEY_EXTREME_BOOST * extreme
    responded = resolved & (rng.random(n) < response_rate)

    tickets["satisfaction_score"] = pd.array(np.where(responded, score, 0), dtype="Int64")
    tickets.loc[~responded, "satisfaction_score"] = pd.NA
    return tickets


def build_tickets(seed: int = config.DEFAULT_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tickets = generate_creation_data(rng)
    tickets["description"] = generate_descriptions(tickets, rng)
    tickets = simulate_resolution(tickets, rng)
    tickets = apply_snapshot(tickets, rng)
    tickets = add_satisfaction(tickets, rng)
    tickets["reassignment_count"] = tickets["reassignment_count"].astype("Int64")
    return tickets[TICKET_COLUMNS]


def build_teams() -> pd.DataFrame:
    return pd.DataFrame({"team": list(config.TEAM_AGENTS), "agents": list(config.TEAM_AGENTS.values())})


def build_sla_policies() -> pd.DataFrame:
    rows = [
        {"ticket_type": ticket_type, "priority": priority, "sla_hours": hours}
        for (ticket_type, priority), hours in config.SLA_HOURS.items()
    ]
    return pd.DataFrame(rows)


def build_subcategories() -> pd.DataFrame:
    """The service catalogue. Simulation parameters such as work-time medians
    are deliberately left out: they are the generator's answer key, not data a
    real service desk would have."""
    rows = [
        {"subcategory": name, "category": sub.category, "ticket_type": sub.ticket_type, "owning_team": sub.team}
        for name, sub in config.SUBCATEGORIES.items()
    ]
    return pd.DataFrame(rows)


def build_calendar_days() -> pd.DataFrame:
    days = pd.date_range(config.START_DATE, config.END_DATE, freq="D")
    periods = [period_on(day) for day in days.date]
    return pd.DataFrame({
        "day": days.date,
        "day_of_week": days.dayofweek + 1,
        "is_weekend": days.dayofweek >= 5,
        "is_holiday": [day in config.HOLIDAYS for day in days.date],
        "academic_period": [period.name if period else "regular" for period in periods],
    })


def write_dataset(output_dir: Path, seed: int = config.DEFAULT_SEED) -> pd.DataFrame:
    """Write every table as CSV and return the tickets."""
    tickets = build_tickets(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    tickets.to_csv(output_dir / "tickets.csv", index=False)
    build_teams().to_csv(output_dir / "teams.csv", index=False)
    build_sla_policies().to_csv(output_dir / "sla_policies.csv", index=False)
    build_subcategories().to_csv(output_dir / "subcategories.csv", index=False)
    build_calendar_days().to_csv(output_dir / "calendar_days.csv", index=False)
    return tickets


def summarize(tickets: pd.DataFrame) -> str:
    """Business-level checks used to tune config.py. Not model metrics."""
    resolved = tickets[tickets["status"] == "resolved"]
    per_day = tickets.groupby(tickets["created_at"].dt.date).size()
    weekend = pd.to_datetime(per_day.index).dayofweek >= 5
    surveyed = resolved["satisfaction_score"].dropna()

    def rates(column):
        return resolved.groupby(column)["sla_breached"].mean().mul(100).round(1).to_dict()

    lines = [
        f"tickets:              {len(tickets):,}",
        f"status:               {tickets['status'].value_counts().to_dict()}",
        f"per day:              weekday {per_day[~weekend].mean():.1f}, weekend {per_day[weekend].mean():.1f}",
        f"breach rate:          {resolved['sla_breached'].mean():.1%}",
        f"breach by priority %: {rates('priority')}",
        f"breach by team %:     {rates('resolved_by_team')}",
        f"resolution hours:     median {resolved['resolution_hours'].median():.1f}, "
        f"p90 {resolved['resolution_hours'].quantile(0.9):.1f}",
        f"reopen rate:          {resolved['reopened'].mean():.1%}",
        f"survey response:      {len(surveyed) / len(resolved):.1%}, mean score {surveyed.mean():.2f}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic OpsPilot service-desk dataset.")
    parser.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    args = parser.parse_args()

    tickets = write_dataset(args.output_dir, args.seed)
    print(summarize(tickets))
    print(f"\nwrote {len(tickets):,} tickets to {args.output_dir}/")


if __name__ == "__main__":
    main()
