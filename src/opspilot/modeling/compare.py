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
from opspilot.modeling.evaluation import cross_validate, select_model, time_folds
from opspilot.modeling.pipelines import (
    INTERACTIONS,
    logistic_regression,
    logistic_regression_grid,
    random_forest,
    random_forest_grid,
    xgboost,
    xgboost_grid,
)

SUMMARY_METRICS = ["average_precision", "roc_auc", "brier", "precision_at_capacity", "recall_at_capacity"]


def candidate_models() -> dict:
    """Name -> unfitted estimator, every model in the comparison.

    Settings were chosen from each family's grid on the validation folds
    (reports/modeling/cv_*_grid.csv):

    - Logistic regression: C=0.1, no class weighting. C from 0.1 to 10 scored
      within 0.01 of each other, so the most regularized of those was taken;
      balanced weights lowered average precision and badly hurt calibration.
    - Random forest: min_samples_leaf=20, max_features=0.5, the best mean
      average precision. Fully grown trees (leaf size 1) scored worst.
    - XGBoost: depth 3, learning rate 0.05, 500 trees, the best mean average
      precision. Every depth-5 setting scored lower than the depth-3 ones.
    """
    return {
        "baseline_prior": DummyClassifier(strategy="prior"),
        "baseline_subcategory_history": FeatureScore("subcategory_breach_rate_prev_90d"),
        "logistic_regression": logistic_regression(C=0.1),
        "logistic_regression_interactions": logistic_regression(C=0.1, interactions=INTERACTIONS),
        "random_forest": random_forest(min_samples_leaf=20, max_features=0.5),
        "xgboost": xgboost(max_depth=3, learning_rate=0.05, n_estimators=500),
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
    "rf_grid": random_forest_grid,
    "xgb_grid": xgboost_grid,
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

    summary = summarize(results)
    with pd.option_context("display.width", 160, "display.max_columns", 20):
        print(summary.round(3))
    print(f"\nper-fold results written to {args.output}")
    if args.candidates == "main":
        print(f"selected by the pre-registered rule: {select_model(summary)}")


if __name__ == "__main__":
    main()
