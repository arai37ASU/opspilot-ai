"""Tests for the modeling configuration and dataset.

The expected counts come from notebook 02, which used the same seed-42 data;
if the generator or the decision record changes, these numbers should change
with it, deliberately.
"""

import pandas as pd
import pytest

from opspilot.modeling import config
from opspilot.modeling.dataset import load_modeling_frame, split_train_test, to_model_inputs

POST_CREATION_COLUMNS = {
    "status", "resolved_at", "resolution_hours", "resolved_by_team",
    "reassignment_count", "reopened", "satisfaction_score",
}


# --- Decision record as code ---------------------------------------------------


def test_feature_lists_do_not_overlap_or_include_excluded_columns():
    assert not set(config.CATEGORICAL_FEATURES) & set(config.NUMERIC_FEATURES)
    assert len(config.FEATURES) == len(set(config.FEATURES))
    assert not set(config.FEATURES) & set(config.EXCLUDED_FEATURES)
    assert not set(config.FEATURES) & POST_CREATION_COLUMNS
    assert config.TARGET not in config.FEATURES


def test_dates_are_in_order():
    starts = config.VALIDATION_FOLD_STARTS
    assert config.MODEL_START < starts[0]
    assert starts == sorted(starts)
    assert starts[-1] < config.TEST_START < config.MODEL_END


def test_to_model_inputs_converts_nullable_types():
    frame = pd.DataFrame({
        config.TARGET: pd.array([True, False], dtype="boolean"),
        **{c: pd.array(["a", "b"], dtype="str") for c in config.CATEGORICAL_FEATURES},
        **{c: pd.array([1, None], dtype="Int64") for c in config.NUMERIC_FEATURES},
    })
    X, y = to_model_inputs(frame)
    assert list(X.columns) == config.FEATURES
    assert (X[config.CATEGORICAL_FEATURES].dtypes == object).all()
    assert (X[config.NUMERIC_FEATURES].dtypes == "float64").all()
    assert X[config.NUMERIC_FEATURES].iloc[1].isna().all()
    assert y.tolist() == [1, 0]


def test_to_model_inputs_rejects_missing_labels():
    frame = pd.DataFrame({config.TARGET: pd.array([True, None], dtype="boolean"),
                          **{c: ["a", "b"] for c in config.CATEGORICAL_FEATURES},
                          **{c: [1.0, 2.0] for c in config.NUMERIC_FEATURES}})
    with pytest.raises(ValueError, match="missing"):
        to_model_inputs(frame)


# --- Against the test database ----------------------------------------------------


@pytest.fixture(scope="module")
def frame(db_conn):
    return load_modeling_frame(db_conn)


@pytest.mark.db
def test_every_feature_exists_in_the_feature_view(db_conn):
    columns = {row[0] for row in db_conn.execute(
        "SELECT attname FROM pg_attribute WHERE attrelid = 'ticket_features'::regclass AND attnum > 0")}
    assert set(config.FEATURES) | {config.TARGET} <= columns
    assert set(config.EXCLUDED_FEATURES) <= columns


@pytest.mark.db
def test_population_is_labelled_and_inside_the_window(frame):
    assert frame[config.TARGET].notna().all()
    assert frame["created_at"].min() >= config.MODEL_START
    assert frame["created_at"].max() < config.MODEL_END
    assert frame["created_at"].is_monotonic_increasing
    assert frame["ticket_id"].is_unique


@pytest.mark.db
def test_split_matches_the_decision_record(frame):
    train, test = split_train_test(frame)
    assert len(train) + len(test) == len(frame)
    assert train["created_at"].max() < config.TEST_START <= test["created_at"].min()
    assert not set(train["ticket_id"]) & set(test["ticket_id"])
    # Counts and base rates recorded in notebook 02 for the seed-42 data.
    assert (len(train), len(test)) == (34_426, 11_747)
    assert train[config.TARGET].astype(bool).mean() == pytest.approx(0.156, abs=0.001)
    assert test[config.TARGET].astype(bool).mean() == pytest.approx(0.157, abs=0.001)


@pytest.mark.db
def test_model_inputs_have_no_missing_values_in_the_window(frame):
    X, y = to_model_inputs(frame)
    assert not X.isna().any().any()  # January 2024 warm-up removed every gap
    assert set(y.unique()) == {0, 1}
    assert len(X) == len(y) == len(frame)
