"""The Phase 5 decision record, as code.

The reasoning for every value here is in the decision record at the end of
notebooks/02_feature_assessment.ipynb, written before any model was trained.
Changing a value means updating that record with a reason first.
"""

import pandas as pd

TARGET = "sla_breached"

# Population: resolved tickets in this window. January 2024 is a warm-up
# month for the history features; the last 14 days lack many outcomes.
MODEL_START = pd.Timestamp("2024-02-01")
MODEL_END = pd.Timestamp("2025-12-18")  # exclusive

# Time-based split. The test period is evaluated once, at the end.
TEST_START = pd.Timestamp("2025-07-01")

# Expanding-window validation inside the training period: each fold trains on
# everything before its start and validates until the next start (the last
# fold ends at TEST_START).
VALIDATION_FOLD_STARTS = [
    pd.Timestamp("2024-10-01"),
    pd.Timestamp("2025-01-01"),
    pd.Timestamp("2025-04-01"),
]

CATEGORICAL_FEATURES = [
    "priority",
    "subcategory",
    "assigned_team",
    "academic_period",
    "requester_type",
    "channel",
]

NUMERIC_FEATURES = [
    "sla_hours",
    "hours_until_staffed",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "is_holiday",
    "team_open_per_agent",
    "subcategory_arrivals_prev_2h",
    "subcategory_arrivals_prev_24h",
    "team_breach_rate_prev_30d",
    "team_resolved_prev_30d",
    "subcategory_breach_rate_prev_90d",
    "subcategory_resolved_prev_90d",
]

FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES

# Columns of ticket_features deliberately left out, with the reason.
EXCLUDED_FEATURES = {
    "category": "fully determined by subcategory",
    "ticket_type": "fully determined by subcategory",
    "team_agents": "fully determined by assigned_team",
    "team_open_at_arrival": "near-copy of team_open_per_agent",
    "team_arrivals_prev_24h": "near-copy of team_open_per_agent",
    "department": "differences explained by issue mix",
    "mentions_urgency": "no effect once priority is known",
    "description_length": "weak and template-driven",
    "description": "text is a separate experiment",
}

# Assumed share of new tickets the desk can review. An assumption, not a
# measurement; results at other capacities are reported alongside.
REVIEW_CAPACITY = 0.10

# A simpler model is chosen if its mean validation average precision is
# within this distance of the best model's.
SELECTION_TOLERANCE = 0.01

RANDOM_SEED = 42
BOOTSTRAP_SAMPLES = 1000
