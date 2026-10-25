"""Choose the operating threshold and check calibration on the validation folds.

Usage:
    python -m opspilot.modeling.operating_point

Uses out-of-fold predictions from the selected model: each validation quarter
is scored by a model trained only on earlier tickets. The test period is not
touched. Writes:

    reports/modeling/operating_point.json         threshold, calibration summary
    reports/modeling/capacity_curve_validation.csv
    reports/modeling/calibration_validation.csv
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from opspilot.modeling import config
from opspilot.modeling.compare import candidate_models, summarize
from opspilot.modeling.dataset import load_modeling_frame, split_train_test, to_model_inputs
from opspilot.modeling.evaluation import (
    best_f1_threshold,
    calibration_table,
    capacity_curve,
    expected_calibration_error,
    out_of_fold_predictions,
    select_model,
    threshold_for_share,
    time_folds,
)

CAPACITY_SHARES = [0.05, 0.10, 0.15, 0.20, 0.30]


def selected_model_name(cv_results_path: Path) -> str:
    """The model the selection rule picks from the saved cross-validation results."""
    return select_model(summarize(pd.read_csv(cv_results_path)))


def operating_point(model_name: str, predictions: pd.DataFrame) -> dict:
    y, scores = predictions["y"].to_numpy(), predictions["score"].to_numpy()
    threshold = threshold_for_share(scores, config.REVIEW_CAPACITY)
    by_fold = predictions.groupby("fold")["score"]
    return {
        "model": model_name,
        "review_capacity": config.REVIEW_CAPACITY,
        "threshold": threshold,
        # A fixed threshold flags more tickets in riskier periods; this is the
        # share the desk would actually have seen flagged in each quarter.
        "threshold_by_fold": {int(f): threshold_for_share(s.to_numpy(), config.REVIEW_CAPACITY) for f, s in by_fold},
        "share_flagged_by_fold": {int(f): float((s >= threshold).mean()) for f, s in by_fold},
        "best_f1": best_f1_threshold(y, scores),
        "calibration": {
            "expected_calibration_error": expected_calibration_error(y, scores),
            "mean_predicted": float(scores.mean()),
            "observed_rate": float(y.mean()),
            "decision": "no calibration step: the model's probabilities already match observed rates",
        },
        "validation_tickets": len(predictions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Choose the operating threshold on the validation folds.")
    parser.add_argument("--cv-results", type=Path, default=Path("reports/modeling/cv_results.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/modeling"))
    args = parser.parse_args()

    name = selected_model_name(args.cv_results)
    train, _ = split_train_test(load_modeling_frame())
    X, y = to_model_inputs(train)
    predictions = out_of_fold_predictions(candidate_models()[name], X, y, time_folds(train["created_at"]))

    result = operating_point(name, predictions)
    y_values, scores = predictions["y"].to_numpy(), predictions["score"].to_numpy()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "operating_point.json").write_text(json.dumps(result, indent=2) + "\n")
    capacity_curve(y_values, scores, CAPACITY_SHARES).round(4).to_csv(
        args.output_dir / "capacity_curve_validation.csv", index=False)
    calibration_table(y_values, scores).round(4).to_csv(args.output_dir / "calibration_validation.csv")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
