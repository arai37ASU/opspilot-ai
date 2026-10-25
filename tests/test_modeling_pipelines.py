import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from opspilot.modeling import config
from opspilot.modeling.pipelines import (
    INTERACTIONS,
    InteractionTerms,
    coefficient_table,
    logistic_regression,
    logistic_regression_grid,
    random_forest,
    random_forest_grid,
    xgboost,
    xgboost_grid,
)


@pytest.fixture
def sample():
    """Small synthetic frame shaped like the model inputs, with a learnable signal."""
    rng = np.random.default_rng(0)
    n = 600
    X = pd.DataFrame({
        "priority": rng.choice(["P1", "P2", "P3", "P4"], n).astype(object),
        "subcategory": rng.choice(["a", "b", "c"], n).astype(object),
        "assigned_team": rng.choice(["t1", "t2"], n).astype(object),
        "academic_period": rng.choice(["regular", "summer"], n).astype(object),
        "requester_type": rng.choice(["student", "staff"], n).astype(object),
        "channel": rng.choice(["portal", "phone"], n).astype(object),
        **{column: rng.normal(size=n) for column in config.NUMERIC_FEATURES},
    })[config.FEATURES]
    y = pd.Series((X["hours_until_staffed"] + rng.normal(scale=0.5, size=n) > 0.8).astype(int))
    return X, y


def test_interaction_terms_by_hand():
    X = pd.DataFrame({"priority": ["P1", "P2", "P1"], "wait": [2.0, 3.0, 5.0]})
    terms = InteractionTerms([("priority", "wait")]).fit(X)
    assert terms.transform(X).tolist() == [[2.0, 0.0], [0.0, 3.0], [5.0, 0.0]]
    assert terms.get_feature_names_out().tolist() == ["wait_x_priority=P1", "wait_x_priority=P2"]


def test_interaction_terms_learn_categories_from_training_data_only():
    train = pd.DataFrame({"priority": ["P1", "P2"], "wait": [1.0, 1.0]})
    new = pd.DataFrame({"priority": ["P4"], "wait": [7.0]})
    terms = InteractionTerms([("priority", "wait")]).fit(train)
    assert terms.transform(new).tolist() == [[0.0, 0.0]]


def test_pipeline_fits_and_returns_probabilities(sample):
    X, y = sample
    model = logistic_regression().fit(X, y)
    probabilities = model.predict_proba(X)[:, 1]
    assert ((probabilities >= 0) & (probabilities <= 1)).all()
    assert np.corrcoef(probabilities, X["hours_until_staffed"])[0, 1] > 0.5


def test_unseen_categories_and_missing_values_do_not_break_prediction(sample):
    X, y = sample
    model = logistic_regression(interactions=INTERACTIONS).fit(X, y)
    new = X.head(3).copy()
    new.loc[new.index[0], "subcategory"] = "never_seen"
    new.loc[new.index[1], "priority"] = "P9"
    new.loc[new.index[2], "team_breach_rate_prev_30d"] = np.nan
    assert np.isfinite(model.predict_proba(new)).all()


def test_scaling_is_fitted_on_training_rows_only(sample):
    X, y = sample
    train = X.iloc[:300]
    model = logistic_regression().fit(train, y.iloc[:300])
    scaler = model.named_steps["preprocess"].named_transformers_["numeric"].named_steps["standardscaler"]
    assert scaler.mean_[: len(config.NUMERIC_FEATURES)] == pytest.approx(train[config.NUMERIC_FEATURES].mean().to_numpy())


def test_coefficient_table_lines_up_with_features(sample):
    X, y = sample
    model = logistic_regression(interactions=INTERACTIONS).fit(X, y)
    table = coefficient_table(model)
    assert len(table) == model.named_steps["model"].coef_.shape[1]
    assert table["coefficient"].abs().is_monotonic_decreasing
    assert table.iloc[0]["feature"] == "numeric__hours_until_staffed"
    assert table["feature"].str.startswith("interactions__").any()


def test_grid_covers_regularization_and_weighting():
    grid = logistic_regression_grid()
    assert len(grid) == 8
    assert {model.named_steps["model"].class_weight for model in grid.values()} == {None, "balanced"}


@pytest.mark.parametrize("make_model", [logistic_regression, lambda: random_forest(n_estimators=30),
                                        lambda: xgboost(n_estimators=30)],
                         ids=["logistic_regression", "random_forest", "xgboost"])
def test_fitting_is_deterministic(sample, make_model):
    X, y = sample
    first = make_model().fit(X, y).predict_proba(X)
    second = make_model().fit(X, y).predict_proba(X)
    assert np.array_equal(first, second)


@pytest.mark.parametrize("make_model", [lambda: random_forest(n_estimators=30), lambda: xgboost(n_estimators=30)],
                         ids=["random_forest", "xgboost"])
def test_tree_models_learn_and_handle_unseen_values(sample, make_model):
    X, y = sample
    model = make_model().fit(X.iloc[:400], y.iloc[:400])
    held_out = model.predict_proba(X.iloc[400:])[:, 1]
    assert roc_auc_score(y.iloc[400:], held_out) > 0.7
    new = X.head(2).copy()
    new.loc[new.index[0], "subcategory"] = "never_seen"
    new.loc[new.index[1], "team_breach_rate_prev_30d"] = np.nan
    assert np.isfinite(model.predict_proba(new)).all()


def test_tree_grids_have_the_planned_sizes():
    assert len(random_forest_grid()) == 6
    assert len(xgboost_grid()) == 8
