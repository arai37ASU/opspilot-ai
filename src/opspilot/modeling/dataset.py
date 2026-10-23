"""The modeling dataset: population, train/test split, and model inputs.

Everything comes from the ticket_features view, which holds only information
known when each ticket was created. This module applies the decision-record
population and split and nothing else; preprocessing such as encoding and
imputation belongs inside the model pipeline, where it is fitted on training
data only.
"""

import pandas as pd
import psycopg

from opspilot.analysis.data import load_features
from opspilot.modeling import config


def load_modeling_frame(conn: psycopg.Connection | None = None) -> pd.DataFrame:
    """Labelled tickets in the modeling window, oldest first.

    Keeps the ticket id and creation time next to the features and target,
    because evaluation needs them for time-ordered folds and per-period results.
    """
    features = load_features(conn)
    in_window = features["created_at"].ge(config.MODEL_START) & features["created_at"].lt(config.MODEL_END)
    frame = features[in_window & features[config.TARGET].notna()]
    columns = ["ticket_id", "created_at", config.TARGET, *config.FEATURES]
    return frame[columns].sort_values(["created_at", "ticket_id"]).reset_index(drop=True)


def split_train_test(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    is_test = frame["created_at"] >= config.TEST_START
    return frame[~is_test].reset_index(drop=True), frame[is_test].reset_index(drop=True)


def to_model_inputs(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Feature matrix and target with plain types scikit-learn handles reliably.

    Categorical columns become Python objects and numeric ones float64, so
    nullable pandas types (Int64, boolean, the pandas 3 string type) never
    reach the model. Missing numeric values become NaN for the pipeline's
    imputer.
    """
    X = pd.DataFrame(index=frame.index)
    for column in config.CATEGORICAL_FEATURES:
        X[column] = frame[column].astype(object)
    for column in config.NUMERIC_FEATURES:
        X[column] = frame[column].astype("float64")

    if frame[config.TARGET].isna().any():
        raise ValueError("target has missing values; filter to labelled tickets first")
    y = frame[config.TARGET].astype(bool).astype(int).rename(config.TARGET)
    return X, y
