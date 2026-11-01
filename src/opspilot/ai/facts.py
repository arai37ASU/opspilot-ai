"""Turn a scored ticket into the facts Claude is allowed to use.

Values are written the way the dashboard shows them, because the number guard
compares Claude's text with this text. The ticket's free-text description is
left out: it is not a model feature, so an explanation does not need it, and
it is the one field a requester controls.
"""

from datetime import datetime

from opspilot.modeling.config import REVIEW_CAPACITY

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WHEN_FORMAT = "%A %d %B %Y at %H:%M"


def _hours(value: float) -> str:
    return f"{value:.1f} hours"


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _count(value: float) -> str:
    return f"{value:.0f}"


def _yes_no(value: float) -> str:
    return "yes" if value else "no"


def _words(value: str) -> str:
    return value.replace("_", " ")


FEATURES = {
    "priority": ("Priority", str),
    "subcategory": ("Issue", _words),
    "assigned_team": ("Assigned team", str),
    "academic_period": ("Academic period", _words),
    "requester_type": ("Requester", _words),
    "channel": ("Channel", _words),
    "sla_hours": ("SLA target", _hours),
    "hours_until_staffed": ("Hours until the team is next staffed", _hours),
    "hour_of_day": ("Hour of day", lambda v: f"{v:02.0f}:00"),
    "day_of_week": ("Day of week", lambda v: DAYS[int(v) - 1]),
    "is_weekend": ("Weekend", _yes_no),
    "is_holiday": ("Holiday", _yes_no),
    "team_open_per_agent": ("Team's open tickets per agent", lambda v: f"{v:.1f}"),
    "subcategory_arrivals_prev_2h": ("Similar tickets in the last 2 hours", _count),
    "subcategory_arrivals_prev_24h": ("Similar tickets in the last 24 hours", _count),
    "team_breach_rate_prev_30d": ("Team's breach rate, last 30 days", _percent),
    "team_resolved_prev_30d": ("Team's resolved tickets, last 30 days", _count),
    "subcategory_breach_rate_prev_90d": ("Issue's breach rate, last 90 days", _percent),
    "subcategory_resolved_prev_90d": ("Issue's resolved tickets, last 90 days", _count),
}


def feature_label(name: str) -> str:
    return FEATURES[name][0]


def feature_value(name: str, value) -> str:
    """A missing history rate (no resolved tickets in the window) arrives as None."""
    return "no history" if value is None else FEATURES[name][1](value)


def risk_label(risk: float) -> str:
    """As the dashboard shows it: a probability is never exactly 0 or 1."""
    if risk < 0.005:
        return "below 1%"
    if risk > 0.995:
        return "above 99%"
    return f"{risk * 100:.0f}%"


def ticket_facts(prediction: dict, created_at: datetime) -> dict:
    """Everything Claude may say about one scored ticket."""
    return {
        "created": created_at.strftime(WHEN_FORMAT),
        "risk_of_missing_sla": risk_label(prediction["risk"]),
        "flagged_for_review": prediction["flagged"],
        "review_threshold": risk_label(prediction["threshold"]),
        "share_of_tickets_the_desk_can_review": f"about {REVIEW_CAPACITY * 100:.0f}%",
        "main_reasons": [
            {"feature": reason["feature"], "label": feature_label(reason["feature"]),
             "value": feature_value(reason["feature"], reason["value"]), "direction": reason["direction"]}
            for reason in prediction["reasons"]
        ],
        "ticket": {feature_label(name): feature_value(name, value) for name, value in prediction["inputs"].items()},
    }
