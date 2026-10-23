"""Validation folds, metrics, and uncertainty for the SLA breach model.

Every candidate model, baselines included, is scored by the same functions on
the same folds, so differences between models come from the models.
"""

from collections.abc import Callable

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from opspilot.modeling import config


def time_folds(created_at: pd.Series) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window folds over the training period.

    Fold k trains on every ticket created before its start date and validates
    on tickets from that date until the next fold's start (or TEST_START).
    Returns positional indices, like scikit-learn's own splitters.
    """
    created_at = created_at.reset_index(drop=True)
    ends = [*config.VALIDATION_FOLD_STARTS[1:], config.TEST_START]
    folds = []
    for start, end in zip(config.VALIDATION_FOLD_STARTS, ends):
        train_index = np.flatnonzero(created_at < start)
        validation_index = np.flatnonzero((created_at >= start) & (created_at < end))
        folds.append((train_index, validation_index))
    return folds


def flag_top_share(scores: np.ndarray, share: float) -> np.ndarray:
    """Mark the highest-scoring `share` of tickets.

    Equivalent to a fixed threshold that flags that share of tickets on
    average. Ties at the cut-off are broken by position, so the result is
    deterministic.
    """
    scores = np.asarray(scores, dtype=float)
    flagged_count = int(round(share * len(scores)))
    order = np.argsort(-scores, kind="stable")
    flagged = np.zeros(len(scores), dtype=bool)
    flagged[order[:flagged_count]] = True
    return flagged


def precision_recall_at_share(y: np.ndarray, scores: np.ndarray, share: float) -> tuple[float, float]:
    """If the desk reviews the top `share` of tickets: what share of the
    reviewed tickets breach (precision), and what share of all breaches is
    reviewed (recall)?"""
    y = np.asarray(y).astype(bool)
    flagged = flag_top_share(scores, share)
    caught = (flagged & y).sum()
    precision = caught / flagged.sum() if flagged.any() else 0.0
    recall = caught / y.sum() if y.any() else 0.0
    return float(precision), float(recall)


def evaluate(y: np.ndarray, scores: np.ndarray, share: float = config.REVIEW_CAPACITY) -> dict[str, float]:
    """All decision-record metrics for one set of predicted probabilities."""
    y = np.asarray(y).astype(int)
    scores = np.asarray(scores, dtype=float)
    precision, recall = precision_recall_at_share(y, scores, share)
    return {
        "n": len(y),
        "base_rate": float(y.mean()),
        "average_precision": float(average_precision_score(y, scores)),
        "roc_auc": float(roc_auc_score(y, scores)),
        "brier": float(brier_score_loss(y, scores)),
        "precision_at_capacity": precision,
        "recall_at_capacity": recall,
    }


def cross_validate(model, X: pd.DataFrame, y: pd.Series, folds: list[tuple[np.ndarray, np.ndarray]]) -> pd.DataFrame:
    """Fit a fresh copy of `model` on each fold's training rows and score its validation rows.

    `model` is any scikit-learn style estimator with predict_proba. clone()
    gives each fold an unfitted copy, so nothing learned in one fold carries
    into the next.
    """
    rows = []
    for number, (train_index, validation_index) in enumerate(folds, start=1):
        fitted = clone(model).fit(X.iloc[train_index], y.iloc[train_index])
        scores = fitted.predict_proba(X.iloc[validation_index])[:, 1]
        rows.append({"fold": number, "n_train": len(train_index),
                     **evaluate(y.iloc[validation_index], scores)})
    return pd.DataFrame(rows)


def bootstrap_interval(
    y: np.ndarray,
    scores: np.ndarray,
    metric: Callable[[np.ndarray, np.ndarray], float],
    n_samples: int = config.BOOTSTRAP_SAMPLES,
    confidence: float = 0.95,
    seed: int = config.RANDOM_SEED,
) -> tuple[float, float]:
    """Percentile bootstrap interval for a metric on a fixed set of predictions.

    Resamples tickets with replacement and recomputes the metric, which shows
    how much the number depends on which tickets happened to be in the test
    period. It does not capture uncertainty from refitting the model.
    """
    y = np.asarray(y)
    scores = np.asarray(scores, dtype=float)
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(n_samples):
        sample = rng.integers(0, len(y), size=len(y))
        if y[sample].min() == y[sample].max():
            continue  # a sample with one class cannot be scored
        values.append(metric(y[sample], scores[sample]))
    tail = (1 - confidence) / 2
    return float(np.quantile(values, tail)), float(np.quantile(values, 1 - tail))
