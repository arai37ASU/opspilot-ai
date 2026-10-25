import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

from opspilot.modeling import config
from opspilot.modeling.baselines import FeatureScore
from opspilot.modeling.compare import compare, summarize
from opspilot.modeling.dataset import load_modeling_frame, split_train_test
from opspilot.modeling.evaluation import (
    best_f1_threshold,
    bootstrap_interval,
    calibration_table,
    capacity_curve,
    cross_validate,
    evaluate,
    expected_calibration_error,
    flag_top_share,
    out_of_fold_predictions,
    precision_recall_at_share,
    select_model,
    threshold_for_share,
    time_folds,
)


# --- Folds ------------------------------------------------------------------------


@pytest.fixture
def created_at():
    return pd.Series(pd.date_range(config.MODEL_START, config.TEST_START, freq="6h", inclusive="left"))


def test_folds_train_only_on_the_past(created_at):
    for train_index, validation_index in time_folds(created_at):
        assert created_at.iloc[train_index].max() < created_at.iloc[validation_index].min()
        assert not set(train_index) & set(validation_index)


def test_folds_expand_and_cover_the_end_of_training(created_at):
    folds = time_folds(created_at)
    train_sizes = [len(train) for train, _ in folds]
    assert train_sizes == sorted(train_sizes) and len(set(train_sizes)) == len(folds)
    last_validation = folds[-1][1]
    assert created_at.iloc[last_validation].max() == created_at.max()
    for (_, validation), start in zip(folds, config.VALIDATION_FOLD_STARTS):
        assert created_at.iloc[validation].min() == start


# --- Metrics ----------------------------------------------------------------------


def test_precision_and_recall_at_share_by_hand():
    y = np.array([1, 0, 1, 0, 0, 0, 0, 0, 1, 0])
    scores = np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0])
    # Top 30% = first three tickets, two of which breached; three breaches in total.
    assert precision_recall_at_share(y, scores, 0.3) == pytest.approx((2 / 3, 2 / 3))


def test_flag_top_share_is_deterministic_with_ties():
    flagged = flag_top_share(np.array([0.5, 0.5, 0.5, 0.1]), 0.5)
    assert flagged.tolist() == [True, True, False, False]


def test_evaluate_matches_scikit_learn():
    rng = np.random.default_rng(0)
    y = rng.random(2000) < 0.2
    scores = np.clip(0.2 + 0.3 * (y - 0.2) + rng.normal(0, 0.15, 2000), 0, 1)
    result = evaluate(y, scores)
    assert result["average_precision"] == pytest.approx(average_precision_score(y, scores))
    assert result["roc_auc"] == pytest.approx(roc_auc_score(y, scores))
    assert result["brier"] == pytest.approx(np.mean((scores - y) ** 2))
    assert result["base_rate"] == pytest.approx(y.mean())


def test_no_information_scores_give_base_rate_and_half():
    y = np.array([1, 0, 0, 0, 1, 0, 0, 0, 0, 0])
    result = evaluate(y, np.full(len(y), 0.2))
    assert result["average_precision"] == pytest.approx(0.2)
    assert result["roc_auc"] == pytest.approx(0.5)


def test_bootstrap_interval_contains_the_estimate_and_is_reproducible():
    rng = np.random.default_rng(0)
    y = rng.random(3000) < 0.15
    scores = np.clip(0.15 + 0.3 * y + rng.normal(0, 0.2, 3000), 0, 1)
    low, high = bootstrap_interval(y, scores, average_precision_score, n_samples=200)
    assert low < average_precision_score(y, scores) < high
    assert bootstrap_interval(y, scores, average_precision_score, n_samples=200) == (low, high)


def test_bootstrap_interval_narrows_with_more_data():
    rng = np.random.default_rng(0)

    def width(n):
        y = rng.random(n) < 0.15
        scores = np.clip(0.15 + 0.3 * y + rng.normal(0, 0.2, n), 0, 1)
        low, high = bootstrap_interval(y, scores, roc_auc_score, n_samples=200)
        return high - low

    assert width(10_000) < width(500)


# --- Calibration and thresholds ---------------------------------------------------


def test_calibration_of_perfectly_calibrated_scores_is_near_zero():
    rng = np.random.default_rng(0)
    scores = rng.uniform(0, 1, 50_000)
    y = rng.random(50_000) < scores  # outcomes drawn at exactly the predicted rate
    assert expected_calibration_error(y, scores) < 0.01


def test_calibration_detects_overconfident_scores():
    rng = np.random.default_rng(0)
    true_rate = rng.uniform(0, 1, 50_000)
    y = rng.random(50_000) < true_rate
    inflated = np.clip(true_rate * 1.5, 0, 1)
    assert expected_calibration_error(y, inflated) > 0.1
    table = calibration_table(y, inflated)
    assert (table["mean_predicted"] >= table["observed_rate"]).all()


def test_threshold_for_share_flags_that_share():
    scores = np.linspace(0, 1, 1000)
    threshold = threshold_for_share(scores, 0.10)
    assert (scores >= threshold).mean() == pytest.approx(0.10)


def test_capacity_curve_trades_precision_for_recall():
    rng = np.random.default_rng(0)
    y = rng.random(5000) < 0.15
    scores = np.clip(0.15 + 0.4 * y + rng.normal(0, 0.2, 5000), 0, 1)
    curve = capacity_curve(y, scores, [0.05, 0.10, 0.20, 0.30])
    assert curve["recall"].is_monotonic_increasing
    assert curve["threshold"].is_monotonic_decreasing


def test_best_f1_threshold_by_hand():
    y = np.array([1, 1, 0, 1, 0, 0])
    scores = np.array([0.9, 0.8, 0.7, 0.6, 0.2, 0.1])
    best = best_f1_threshold(y, scores)
    # Flagging the top four (threshold 0.6) catches all three positives with precision 3/4: F1 = 6/7.
    assert best["threshold"] == pytest.approx(0.6)
    assert best["f1"] == pytest.approx(6 / 7)
    assert best["share_flagged"] == pytest.approx(4 / 6)


def test_operating_point_summary():
    from opspilot.modeling.operating_point import operating_point

    rng = np.random.default_rng(0)
    y = rng.random(3000) < 0.15
    predictions = pd.DataFrame({"fold": np.repeat([1, 2, 3], 1000), "y": y.astype(int),
                                "score": np.clip(0.15 + 0.4 * y + rng.normal(0, 0.2, 3000), 0, 1)})
    result = operating_point("xgboost", predictions)
    assert (predictions["score"] >= result["threshold"]).mean() == pytest.approx(config.REVIEW_CAPACITY)
    assert sum(result["share_flagged_by_fold"].values()) / 3 == pytest.approx(config.REVIEW_CAPACITY)
    assert set(result["threshold_by_fold"]) == {1, 2, 3}


def test_out_of_fold_predictions_cover_each_validation_row_once(created_at):
    X = pd.DataFrame({"x": np.arange(len(created_at), dtype=float)})
    y = pd.Series((np.arange(len(created_at)) % 5 == 0).astype(int))
    folds = time_folds(created_at)
    predictions = out_of_fold_predictions(DummyClassifier(strategy="prior"), X, y, folds)
    expected = np.concatenate([validation for _, validation in folds])
    assert predictions["position"].tolist() == expected.tolist()
    assert predictions["y"].tolist() == y.iloc[expected].tolist()


# --- Selection rule ---------------------------------------------------------------


def summary_with(**scores):
    return pd.DataFrame({"average_precision_mean": scores})


def test_selection_picks_the_best_when_nothing_simpler_is_close():
    summary = summary_with(logistic_regression=0.60, random_forest=0.65, xgboost=0.70)
    assert select_model(summary) == "xgboost"


def test_selection_prefers_a_simpler_model_within_tolerance():
    summary = summary_with(logistic_regression=0.640, logistic_regression_interactions=0.652, xgboost=0.658)
    assert select_model(summary) == "logistic_regression_interactions"


def test_selection_tolerance_boundary_is_inclusive():
    summary = summary_with(logistic_regression=0.65, xgboost=0.66)
    assert select_model(summary, tolerance=0.01) == "logistic_regression"
    assert select_model(summary, tolerance=0.009) == "xgboost"


def test_every_model_in_the_simplicity_order_is_a_candidate():
    from opspilot.modeling.compare import candidate_models

    names = set(candidate_models())
    assert set(config.SIMPLICITY_ORDER) <= names
    assert {name for name in names if not name.startswith("baseline_")} == set(config.SIMPLICITY_ORDER)


def test_selection_ignores_baselines():
    summary = summary_with(baseline_prior=0.99, logistic_regression=0.5)
    assert select_model(summary) == "logistic_regression"


# --- Baselines and cross-validation ------------------------------------------------


def test_feature_score_uses_the_column_and_falls_back_for_missing_values():
    X = pd.DataFrame({"rate": [0.1, np.nan, 0.8]})
    model = FeatureScore("rate").fit(X, pd.Series([0, 1, 1, 0]))
    assert model.predict_proba(X)[:, 1] == pytest.approx([0.1, 0.5, 0.8])
    assert model.predict(X).tolist() == [0, 1, 1]


def test_cross_validate_refits_a_fresh_model_per_fold(created_at):
    X = pd.DataFrame({"x": np.arange(len(created_at), dtype=float)})
    y = pd.Series((np.arange(len(created_at)) % 7 == 0).astype(int))
    results = cross_validate(DummyClassifier(strategy="prior"), X, y, time_folds(created_at))
    assert results["fold"].tolist() == [1, 2, 3]
    assert results["roc_auc"].tolist() == pytest.approx([0.5, 0.5, 0.5])


@pytest.mark.db
def test_baselines_on_the_real_folds(db_conn):
    train, _ = split_train_test(load_modeling_frame(db_conn))
    results = compare(train, {
        "baseline_prior": DummyClassifier(strategy="prior"),
        "baseline_subcategory_history": FeatureScore("subcategory_breach_rate_prev_90d"),
    })
    assert len(results) == 6
    summary = summarize(results)
    prior = summary.loc["baseline_prior"]
    history = summary.loc["baseline_subcategory_history"]
    # The no-information baseline scores the base rate; the history feature must do better.
    assert prior["roc_auc_mean"] == pytest.approx(0.5)
    assert history["average_precision_mean"] > prior["average_precision_mean"]


@pytest.mark.db
def test_model_cannot_learn_shuffled_labels(db_conn):
    """A leakage canary: with labels shuffled, nothing real is left to learn,
    so any score clearly above chance means information is leaking through
    the features or the pipeline."""
    from opspilot.modeling.dataset import to_model_inputs
    from opspilot.modeling.pipelines import logistic_regression

    train, _ = split_train_test(load_modeling_frame(db_conn))
    X, y = to_model_inputs(train)
    shuffled = pd.Series(np.random.default_rng(0).permutation(y.to_numpy()), index=y.index)
    results = cross_validate(logistic_regression(C=0.1), X, shuffled, time_folds(train["created_at"]))
    assert results["roc_auc"].mean() == pytest.approx(0.5, abs=0.02)
    assert results["average_precision"].mean() == pytest.approx(shuffled.mean(), abs=0.02)
