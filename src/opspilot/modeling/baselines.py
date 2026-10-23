"""Baselines a model has to beat.

The no-information baseline is scikit-learn's DummyClassifier(strategy="prior"),
which predicts the training breach rate for every ticket. This module adds
the second baseline from the decision record: a single feature used directly
as the predicted probability.
"""

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin


class FeatureScore(ClassifierMixin, BaseEstimator):
    """Predicts with one column that is already a probability, such as a
    historical breach rate. Fitting learns nothing except a fallback for
    missing values."""

    def __init__(self, column: str):
        self.column = column

    def fit(self, X: pd.DataFrame, y: pd.Series):
        self.classes_ = np.array([0, 1])
        self.fallback_ = float(np.mean(y))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        probability = X[self.column].astype("float64").fillna(self.fallback_).clip(0, 1).to_numpy()
        return np.column_stack([1 - probability, probability])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)
