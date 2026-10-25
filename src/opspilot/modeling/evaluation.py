"""Validation folds, metrics, and uncertainty for the SLA breach model.

Every candidate model, baselines included, is scored by the same functions on
the same folds, so differences between models come from the models.
"""

from collections.abc import Callable

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score

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
    predictions = out_of_fold_predictions(model, X, y, folds)
    rows = []
    for number, (train_index, _) in enumerate(folds, start=1):
        fold = predictions[predictions["fold"] == number]
        rows.append({"fold": number, "n_train": len(train_index), **evaluate(fold["y"], fold["score"])})
    return pd.DataFrame(rows)


def out_of_fold_predictions(model, X: pd.DataFrame, y: pd.Series,
                            folds: list[tuple[np.ndarray, np.ndarray]]) -> pd.DataFrame:
    """Validation-set predictions from every fold, each made by a model that
    never saw those tickets. Columns: position (row in X), fold, y, score."""
    parts = []
    for number, (train_index, validation_index) in enumerate(folds, start=1):
        fitted = clone(model).fit(X.iloc[train_index], y.iloc[train_index])
        parts.append(pd.DataFrame({
            "position": validation_index,
            "fold": number,
            "y": y.iloc[validation_index].to_numpy(),
            "score": fitted.predict_proba(X.iloc[validation_index])[:, 1],
        }))
    return pd.concat(parts, ignore_index=True)


def calibration_table(y: np.ndarray, scores: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Mean predicted probability against the observed rate in equal-sized risk bands."""
    frame = pd.DataFrame({"y": np.asarray(y, dtype=float), "score": np.asarray(scores, dtype=float)})
    frame["band"] = pd.qcut(frame["score"], bins, labels=False, duplicates="drop")
    return frame.groupby("band").agg(n=("y", "size"), mean_predicted=("score", "mean"), observed_rate=("y", "mean"))


def expected_calibration_error(y: np.ndarray, scores: np.ndarray, bins: int = 10) -> float:
    """Average gap between predicted and observed rates across risk bands,
    weighted by band size. 0 means predictions match outcomes on average."""
    table = calibration_table(y, scores, bins)
    weights = table["n"] / table["n"].sum()
    return float((weights * (table["mean_predicted"] - table["observed_rate"]).abs()).sum())


def threshold_for_share(scores: np.ndarray, share: float) -> float:
    """The probability cut-off that flags `share` of these tickets.

    It is the lowest score among the flagged tickets, so applying
    `score >= threshold` to the same scores flags that share (more if
    several tickets tie at the cut-off).
    """
    flagged = flag_top_share(scores, share)
    return float(np.asarray(scores, dtype=float)[flagged].min())


def threshold_metrics(y: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, float]:
    """Outcomes of flagging every ticket with `score >= threshold`.

    Unlike precision_recall_at_share, the share flagged is not fixed: it is
    whatever the threshold produces on these tickets, which is how a deployed
    threshold behaves.
    """
    y = np.asarray(y).astype(bool)
    flagged = np.asarray(scores, dtype=float) >= threshold
    true_positives = int((flagged & y).sum())
    false_positives = int((flagged & ~y).sum())
    false_negatives = int((~flagged & y).sum())
    true_negatives = int((~flagged & ~y).sum())
    return {
        "share_flagged": float(flagged.mean()),
        "precision": true_positives / flagged.sum() if flagged.any() else 0.0,
        "recall": true_positives / y.sum() if y.any() else 0.0,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "true_negatives": true_negatives,
    }


def capacity_curve(y: np.ndarray, scores: np.ndarray, shares: list[float]) -> pd.DataFrame:
    """Precision and recall if the desk could review different shares of tickets."""
    rows = []
    for share in shares:
        precision, recall = precision_recall_at_share(y, scores, share)
        rows.append({"review_share": share, "threshold": threshold_for_share(scores, share),
                     "precision": precision, "recall": recall})
    return pd.DataFrame(rows)


def best_f1_threshold(y: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    """The threshold with the highest F1, for comparison with the capacity-based one."""
    precision, recall, thresholds = precision_recall_curve(y, scores)
    f1 = 2 * precision * recall / np.where(precision + recall == 0, 1, precision + recall)
    best = int(np.argmax(f1[:-1]))  # the last point has no threshold
    threshold = float(thresholds[best])
    return {"threshold": threshold, "precision": float(precision[best]), "recall": float(recall[best]),
            "f1": float(f1[best]), "share_flagged": float((np.asarray(scores) >= threshold).mean())}


def select_model(
    summary: pd.DataFrame,
    simplicity_order: list[str] = config.SIMPLICITY_ORDER,
    tolerance: float = config.SELECTION_TOLERANCE,
) -> str:
    """Apply the pre-registered selection rule.

    Among eligible models, find the best mean validation average precision;
    then choose the simplest model whose mean is within `tolerance` of it.
    `summary` is indexed by model name with an `average_precision_mean` column.
    """
    eligible = summary.loc[[name for name in simplicity_order if name in summary.index], "average_precision_mean"]
    if eligible.empty:
        raise ValueError("no eligible models in the summary")
    close_enough = eligible[eligible >= eligible.max() - tolerance]
    return next(name for name in simplicity_order if name in close_enough.index)


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
