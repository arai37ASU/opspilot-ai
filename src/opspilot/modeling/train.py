"""Fit the selected model on all training data and evaluate it once on the test period.

Usage:
    python -m opspilot.modeling.train

This is the only place the test period is scored. Everything it uses was
fixed beforehand on the validation folds: the model (selection rule applied
to reports/modeling/cv_results.csv) and the threshold
(reports/modeling/operating_point.json).

Two guards keep the evaluation honest:
- it refuses to run on uncommitted code, so the result can be traced to an
  exact commit (override with --allow-uncommitted);
- it refuses to overwrite an existing result (override with --rerun), so the
  test set is not scored again and again while changes are made.

Writes the fitted pipeline to models/ (not version-controlled; rebuild with
this command) and the results to reports/modeling/test_*.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from opspilot.modeling import config
from opspilot.modeling.compare import candidate_models
from opspilot.modeling.dataset import load_modeling_frame, split_train_test, to_model_inputs
from opspilot.modeling.evaluation import (
    bootstrap_interval,
    calibration_table,
    evaluate,
    expected_calibration_error,
    threshold_metrics,
)
from opspilot.modeling.operating_point import selected_model_name

# Reported next to the selected model so its gain can be judged.
REFERENCE_MODELS = ["baseline_prior", "baseline_subcategory_history", "logistic_regression_interactions"]
MIN_GROUP_SIZE = 200  # smaller groups are reported but flagged as too small to read


def git_state() -> dict:
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()

    return {"commit": git("rev-parse", "HEAD"), "uncommitted_changes": bool(git("status", "--porcelain"))}


def fit_and_score(model, X_train, y_train, X_test):
    fitted = model.fit(X_train, y_train)
    return fitted, fitted.predict_proba(X_test)[:, 1]


def overall_results(y, scores, threshold: float) -> dict:
    metrics = {k: v for k, v in evaluate(y, scores).items()
               if k not in ("precision_at_capacity", "recall_at_capacity")}
    intervals = {
        "average_precision": bootstrap_interval(y, scores, average_precision_score),
        "roc_auc": bootstrap_interval(y, scores, roc_auc_score),
        "brier": bootstrap_interval(y, scores, brier_score_loss),
        "precision_at_threshold": bootstrap_interval(y, scores, lambda t, s: threshold_metrics(t, s, threshold)["precision"]),
        "recall_at_threshold": bootstrap_interval(y, scores, lambda t, s: threshold_metrics(t, s, threshold)["recall"]),
    }
    return {
        **metrics,
        "at_threshold": threshold_metrics(y, scores, threshold),
        "expected_calibration_error": expected_calibration_error(y, scores),
        "intervals_95": intervals,
    }


def results_by(test: pd.DataFrame, scores, threshold: float, group: pd.Series) -> pd.DataFrame:
    """Metrics per group (team, month). Groups too small or with one outcome get NaN for ranking metrics."""
    rows = []
    y = test[config.TARGET].astype(bool).astype(int).to_numpy()
    for name, positions in group.groupby(group).indices.items():
        g_y, g_scores = y[positions], scores[positions]
        both_classes = 0 < g_y.sum() < len(g_y)
        at = threshold_metrics(g_y, g_scores, threshold)
        rows.append({
            "group": name,
            "n": len(g_y),
            "base_rate": g_y.mean(),
            "average_precision": average_precision_score(g_y, g_scores) if both_classes else float("nan"),
            "roc_auc": roc_auc_score(g_y, g_scores) if both_classes else float("nan"),
            "share_flagged": at["share_flagged"],
            "precision_at_threshold": at["precision"],
            "recall_at_threshold": at["recall"],
            "small_group": len(g_y) < MIN_GROUP_SIZE,
        })
    return pd.DataFrame(rows)


def run(frame: pd.DataFrame, model_name: str, threshold: float) -> dict:
    """Fit on train, score test. Returns everything main() saves."""
    train, test = split_train_test(frame)
    X_train, y_train = to_model_inputs(train)
    X_test, y_test = to_model_inputs(test)
    models = candidate_models()

    fitted, scores = fit_and_score(models[model_name], X_train, y_train, X_test)
    references = {name: fit_and_score(models[name], X_train, y_train, X_test)[1]
                  for name in REFERENCE_MODELS if name != model_name}

    return {
        "fitted": fitted,
        "summary": {
            "model": model_name,
            "threshold": threshold,
            "train_period": [str(train["created_at"].min()), str(train["created_at"].max())],
            "test_period": [str(test["created_at"].min()), str(test["created_at"].max())],
            "train_tickets": len(train),
            "test_tickets": len(test),
            "selected": overall_results(y_test.to_numpy(), scores, threshold),
            "references": {name: {k: v for k, v in evaluate(y_test, s).items() if k != "n"}
                           for name, s in references.items()},
        },
        "by_team": results_by(test, scores, threshold, test["assigned_team"]),
        "by_month": results_by(test, scores, threshold, test["created_at"].dt.to_period("M").astype(str)),
        "calibration": calibration_table(y_test.to_numpy(), scores),
        "predictions": pd.DataFrame({"ticket_id": test["ticket_id"], "created_at": test["created_at"],
                                     "assigned_team": test["assigned_team"], "y": y_test, "score": scores}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit the selected model and evaluate it once on the test period.")
    parser.add_argument("--reports-dir", type=Path, default=Path("reports/modeling"))
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    parser.add_argument("--rerun", action="store_true", help="overwrite an existing test result")
    parser.add_argument("--allow-uncommitted", action="store_true", help="run even with uncommitted changes")
    args = parser.parse_args()

    results_path = args.reports_dir / "test_results.json"
    if results_path.exists() and not args.rerun:
        sys.exit(f"{results_path} already exists. The test set is scored once; use --rerun only with a written reason.")
    state = git_state()
    if state["uncommitted_changes"] and not args.allow_uncommitted:
        sys.exit("Uncommitted changes: commit first so the test result can be traced to exact code.")

    model_name = selected_model_name(args.reports_dir / "cv_results.csv")
    threshold = json.loads((args.reports_dir / "operating_point.json").read_text())["threshold"]
    result = run(load_modeling_frame(), model_name, threshold)

    summary = {
        **result["summary"],
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": state,
        "versions": {package: version(package) for package in ["scikit-learn", "xgboost", "pandas", "numpy"]},
    }
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(summary, indent=2, default=float) + "\n")
    result["by_team"].round(4).to_csv(args.reports_dir / "test_by_team.csv", index=False)
    result["by_month"].round(4).to_csv(args.reports_dir / "test_by_month.csv", index=False)
    result["calibration"].round(4).to_csv(args.reports_dir / "test_calibration.csv")

    args.models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(result["fitted"], args.models_dir / "sla_breach_model.joblib")
    (args.models_dir / "sla_breach_model.json").write_text(json.dumps({
        "model": model_name, "threshold": threshold, "features": config.FEATURES,
        "train_period": summary["train_period"], "git": state, "versions": summary["versions"],
    }, indent=2) + "\n")
    result["predictions"].to_csv(args.models_dir / "test_predictions.csv", index=False)

    print(f"evaluated {model_name} on {summary['test_tickets']:,} test tickets; results in {args.reports_dir}/test_*")


if __name__ == "__main__":
    main()
