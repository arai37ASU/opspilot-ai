"""Compare candidate models on the validation folds.

Usage:
    python -m opspilot.modeling.compare --output reports/modeling/cv_results.csv

Every candidate is cross-validated on the same three expanding-window folds
inside the training period. The test period is never touched here.
"""

import argparse
from pathlib import Path

import pandas as pd
from sklearn.dummy import DummyClassifier

from opspilot.modeling.baselines import FeatureScore
from opspilot.modeling.dataset import load_modeling_frame, split_train_test, to_model_inputs
from opspilot.modeling.evaluation import cross_validate, time_folds
from opspilot.modeling.pipelines import INTERACTIONS, logistic_regression, logistic_regression_grid

SUMMARY_METRICS = ["average_precision", "roc_auc", "brier", "precision_at_capacity", "recall_at_capacity"]


def candidate_models() -> dict:
    """Name -> unfitted estimator, every model in the comparison.

    Logistic regression uses C=0.1 and no class weighting, chosen from
    logistic_regression_grid() on the validation folds
    (reports/modeling/cv_logreg_grid.csv): C from 0.1 to 10 scored within
    0.01 of each other, so the most regularized of those was taken, and
    balanced weights lowered average precision and badly hurt calibration.
    """
    return {
        "baseline_prior": DummyClassifier(strategy="prior"),
        "baseline_subcategory_history": FeatureScore("subcategory_breach_rate_prev_90d"),
        "logistic_regression": logistic_regression(C=0.1),
        "logistic_regression_interactions": logistic_regression(C=0.1, interactions=INTERACTIONS),
    }


def compare(train: pd.DataFrame, candidates: dict) -> pd.DataFrame:
    X, y = to_model_inputs(train)
    folds = time_folds(train["created_at"])
    results = [cross_validate(model, X, y, folds).assign(model=name) for name, model in candidates.items()]
    return pd.concat(results, ignore_index=True)[["model", *results[0].columns.drop("model")]]


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    """Mean and fold-to-fold standard deviation of each metric, per model."""
    summary = results.groupby("model", sort=False)[SUMMARY_METRICS].agg(["mean", "std"])
    summary.columns = [f"{metric}_{stat}" for metric, stat in summary.columns]
    return summary.sort_values("average_precision_mean", ascending=False)


CANDIDATE_SETS = {
    "main": candidate_models,
    "logreg_grid": logistic_regression_grid,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-validate candidate SLA breach models.")
    parser.add_argument("--candidates", choices=CANDIDATE_SETS, default="main")
    parser.add_argument("--output", type=Path, default=Path("reports/modeling/cv_results.csv"))
    args = parser.parse_args()

    train, _ = split_train_test(load_modeling_frame())
    results = compare(train, CANDIDATE_SETS[args.candidates]())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results.round(4).to_csv(args.output, index=False)

    with pd.option_context("display.width", 160, "display.max_columns", 20):
        print(summarize(results).round(3))
    print(f"\nper-fold results written to {args.output}")


if __name__ == "__main__":
    main()
