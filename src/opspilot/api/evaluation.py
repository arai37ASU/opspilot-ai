"""The saved evaluation of the deployed model, for the dashboard's model page.

Everything here was computed once by the modeling commands (train, explain)
and saved under reports/modeling. The API only reads those files; it never
re-evaluates the model, so the numbers are the ones the model card reports.
"""

import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Request

from opspilot.api.schemas import ModelEvaluation

router = APIRouter(tags=["model"])

# Baselines in test_results.json, in the order the page shows them.
COMPARISON = [
    ("baseline_prior", "Base rate only"),
    ("baseline_subcategory_history", "Issue's recent breach rate"),
    ("logistic_regression_interactions", "Logistic regression"),
]
GROUP_COLUMNS = ["group", "n", "base_rate", "average_precision", "share_flagged",
                 "precision_at_threshold", "recall_at_threshold", "small_group"]


def load_evaluation(reports_dir: Path) -> dict:
    """Combine the saved reports into one response body."""
    results = json.loads((reports_dir / "test_results.json").read_text())
    examples = json.loads((reports_dir / "example_explanations.json").read_text())["examples"]
    selected = results["selected"]
    at_threshold = selected["at_threshold"]

    comparison = [{"name": label, "selected": False, **_scores(results["references"][key])} for key, label in COMPARISON]
    comparison.append({"name": f"{results['model']} (deployed)", "selected": True, **_scores(selected)})

    return {
        "model": results["model"],
        "threshold": results["threshold"],
        "train_period": results["train_period"],
        "test_period": results["test_period"],
        "train_tickets": results["train_tickets"],
        "test_tickets": results["test_tickets"],
        "base_rate": selected["base_rate"],
        "average_precision": selected["average_precision"],
        "roc_auc": selected["roc_auc"],
        "brier": selected["brier"],
        "expected_calibration_error": selected["expected_calibration_error"],
        "intervals_95": selected["intervals_95"],
        "at_threshold": at_threshold,
        "comparison": comparison,
        "capacity_curve": _csv(reports_dir / "capacity_curve_validation.csv"),
        "calibration": _csv(reports_dir / "test_calibration.csv"),
        "feature_importance": _csv(reports_dir / "feature_importance.csv"),
        "by_team": _csv(reports_dir / "test_by_team.csv", GROUP_COLUMNS),
        "by_month": _csv(reports_dir / "test_by_month.csv", GROUP_COLUMNS),
        "examples": [{"case": case, **{key: example[key] for key in ("ticket_id", "predicted_risk", "breached")}}
                     for case, example in examples.items()],
        "evaluated_at": results["evaluated_at"],
        "commit": results["git"]["commit"],
        "versions": results["versions"],
    }


def _scores(metrics: dict) -> dict:
    return {key: metrics[key] for key in ("average_precision", "roc_auc", "brier")}


def _csv(path: Path, columns: list[str] | None = None) -> list[dict]:
    frame = pd.read_csv(path)
    return frame[columns or list(frame.columns)].to_dict(orient="records")


@router.get("/model/evaluation", response_model=ModelEvaluation)
def evaluation(request: Request):
    """How the deployed model did on the held-out test period, with baselines,
    calibration, the review-capacity trade-off, feature importance, results
    by team and month, and example tickets. Read from the saved reports."""
    return request.app.state.evaluation
