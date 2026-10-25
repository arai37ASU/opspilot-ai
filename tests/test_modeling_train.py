"""Tests for the final evaluation.

These check structure and behavior only. They deliberately never assert or
print test-period metric values, so running the suite does not amount to
looking at the test set.
"""

import json
import subprocess

import joblib
import numpy as np
import pandas as pd
import pytest

from opspilot.modeling import config, train as train_module
from opspilot.modeling.dataset import load_modeling_frame, split_train_test, to_model_inputs
from opspilot.modeling.evaluation import threshold_metrics


def test_threshold_metrics_by_hand():
    y = np.array([1, 0, 1, 0, 1])
    scores = np.array([0.9, 0.8, 0.4, 0.3, 0.6])
    result = threshold_metrics(y, scores, 0.5)  # flags tickets 0, 1, 4
    assert result["share_flagged"] == pytest.approx(3 / 5)
    assert result["precision"] == pytest.approx(2 / 3)
    assert result["recall"] == pytest.approx(2 / 3)
    assert (result["true_positives"], result["false_positives"],
            result["false_negatives"], result["true_negatives"]) == (2, 1, 1, 1)


def test_git_state_reports_a_commit():
    state = train_module.git_state()
    assert len(state["commit"]) == 40
    assert isinstance(state["uncommitted_changes"], bool)


def test_refuses_to_overwrite_an_existing_result(tmp_path, monkeypatch):
    (tmp_path / "test_results.json").write_text("{}")
    monkeypatch.setattr("sys.argv", ["train", "--reports-dir", str(tmp_path)])
    with pytest.raises(SystemExit, match="already exists"):
        train_module.main()


def test_refuses_to_run_on_uncommitted_code(tmp_path, monkeypatch):
    monkeypatch.setattr(train_module, "git_state", lambda: {"commit": "x" * 40, "uncommitted_changes": True})
    monkeypatch.setattr("sys.argv", ["train", "--reports-dir", str(tmp_path)])
    with pytest.raises(SystemExit, match="Uncommitted"):
        train_module.main()


@pytest.fixture(scope="module")
def result(db_conn):
    # A fast baseline stands in for the selected model; the structure is the same.
    return train_module.run(load_modeling_frame(db_conn), "baseline_subcategory_history", threshold=0.3)


@pytest.mark.db
def test_run_fits_on_train_and_scores_every_test_ticket(result, db_conn):
    _, test = split_train_test(load_modeling_frame(db_conn))
    predictions = result["predictions"]
    assert len(predictions) == len(test) == result["summary"]["test_tickets"]
    assert (predictions["created_at"] >= config.TEST_START).all()
    assert predictions["score"].between(0, 1).all()


@pytest.mark.db
def test_summary_has_the_decision_record_metrics(result):
    selected = result["summary"]["selected"]
    for metric in ["average_precision", "roc_auc", "brier", "expected_calibration_error", "at_threshold"]:
        assert metric in selected
    for metric, (low, high) in selected["intervals_95"].items():
        assert low <= high, metric
    assert set(result["summary"]["references"]) == set(train_module.REFERENCE_MODELS) - {"baseline_subcategory_history"}
    json.dumps(result["summary"], default=float)  # must be serializable


@pytest.mark.db
def test_breakdowns_cover_every_team_and_month(result, db_conn):
    _, test = split_train_test(load_modeling_frame(db_conn))
    assert set(result["by_team"]["group"]) == set(test["assigned_team"])
    assert result["by_team"]["n"].sum() == len(test)
    assert result["by_month"]["n"].sum() == len(test)


@pytest.mark.db
def test_saved_model_reproduces_its_predictions(result, db_conn, tmp_path):
    path = tmp_path / "model.joblib"
    joblib.dump(result["fitted"], path)
    _, test = split_train_test(load_modeling_frame(db_conn))
    X_test, _ = to_model_inputs(test)
    reloaded = joblib.load(path).predict_proba(X_test)[:, 1]
    assert np.array_equal(reloaded, result["predictions"]["score"].to_numpy())


def test_models_directory_is_not_version_controlled():
    ignored = subprocess.run(["git", "check-ignore", "models/sla_breach_model.joblib"], capture_output=True)
    assert ignored.returncode == 0
