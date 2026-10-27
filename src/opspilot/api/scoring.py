"""Turn one row of model features into a scored, explained prediction."""

import math

import pandas as pd
from sklearn.pipeline import Pipeline

from opspilot.modeling.explain import shap_by_feature, ticket_reasons

TOP_REASONS = 3


def score(model: Pipeline, threshold: float, model_name: str, features: pd.DataFrame) -> dict:
    """Risk, flag, and top reasons for a single-row feature matrix."""
    if len(features) != 1:
        raise ValueError("score() expects exactly one ticket")
    risk = float(model.predict_proba(features)[0, 1])
    contributions, _ = shap_by_feature(model, features)
    reasons = [
        {**reason, "direction": "raises risk" if reason["contribution"] > 0 else "lowers risk"}
        for reason in ticket_reasons(contributions.iloc[0], features.iloc[0], top=TOP_REASONS)
    ]
    inputs = {name: _json_value(value) for name, value in features.iloc[0].items()}
    return {"risk": risk, "flagged": risk >= threshold, "threshold": threshold,
            "reasons": reasons, "inputs": inputs, "model": model_name}


def _json_value(value):
    """Plain Python value, with NaN (a missing history rate) as None."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value.item() if hasattr(value, "item") else value
