"""Tests for model explanations.

Uses a small XGBoost model fitted on part of the training period, so the tests
do not depend on the saved artifact in models/.
"""

import numpy as np
import pandas as pd
import pytest

from opspilot.modeling import config
from opspilot.modeling.dataset import load_modeling_frame, split_train_test, to_model_inputs
from opspilot.modeling.explain import (
    encoded_feature_owners,
    example_tickets,
    permutation_importance_table,
    shap_by_feature,
    shap_importance,
    ticket_reasons,
)
from opspilot.modeling.pipelines import xgboost

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def fitted(db_conn):
    train, _ = split_train_test(load_modeling_frame(db_conn))
    X, y = to_model_inputs(train)
    model = xgboost(max_depth=3, n_estimators=50).fit(X.iloc[:15_000], y.iloc[:15_000])
    return model, X.iloc[15_000:17_000], y.iloc[15_000:17_000]


def test_every_encoded_column_has_an_original_feature(fitted):
    model, _, _ = fitted
    owners = encoded_feature_owners(model)
    assert len(owners) == len(model.named_steps["preprocess"].get_feature_names_out())
    assert set(owners) == set(config.FEATURES)


def test_grouped_shap_values_add_up_to_the_model_output(fitted):
    model, X, _ = fitted
    grouped, base_value = shap_by_feature(model, X)
    assert list(grouped.columns) == config.FEATURES
    encoded = model.named_steps["preprocess"].transform(X)
    margin = model.named_steps["model"].predict(encoded, output_margin=True)
    assert np.allclose(grouped.sum(axis=1) + base_value, margin, atol=1e-4)


def test_preprocessor_output_is_always_sparse(fitted):
    """Dense output would change how XGBoost reads zeros (see tree_preprocessor)."""
    from scipy import sparse

    model, X, _ = fitted
    preprocess = model.named_steps["preprocess"]
    assert sparse.issparse(preprocess.transform(X))
    assert sparse.issparse(preprocess.transform(X.iloc[[0]]))


def test_a_ticket_scores_the_same_alone_or_in_a_batch(fitted):
    model, X, _ = fitted
    batch = model.predict_proba(X.iloc[:50])[:, 1]
    alone = np.array([model.predict_proba(X.iloc[[i]])[0, 1] for i in range(50)])
    assert np.array_equal(batch, alone)


def test_importance_tables_cover_every_feature(fitted):
    model, X, y = fitted
    grouped, _ = shap_by_feature(model, X)
    shap_table = shap_importance(grouped)
    assert set(shap_table["feature"]) == set(config.FEATURES)
    assert shap_table["mean_abs_shap"].is_monotonic_decreasing
    permutation = permutation_importance_table(model, X, y, n_repeats=2)
    assert set(permutation["feature"]) == set(config.FEATURES)


def test_ticket_reasons_are_the_largest_contributions():
    contributions = pd.Series({"a": 0.1, "b": -0.9, "c": 0.5, "d": 0.0})
    values = pd.Series({"a": 1, "b": "P4", "c": 3.5, "d": 0})
    reasons = ticket_reasons(contributions, values, top=2)
    assert [r["feature"] for r in reasons] == ["b", "c"]
    assert reasons[0] == {"feature": "b", "value": "P4", "contribution": -0.9}


def test_example_tickets_pick_one_of_each_outcome():
    test = pd.DataFrame({config.TARGET: [True, False, True, False, True]})
    scores = np.array([0.9, 0.8, 0.2, 0.1, 0.6])
    picks = example_tickets(test, scores, threshold=0.5)
    assert picks == {"caught_breach": 0, "false_alarm": 1, "missed_breach": 2}
