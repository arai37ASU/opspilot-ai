"""Model pipelines for SLA breach prediction.

Every transformation (encoding, imputation, scaling, interaction terms) is a
step inside a scikit-learn Pipeline, so it is fitted on the training rows of
each fold and only applied to validation or test rows. Fitting any of them on
the full dataset first would leak information from the evaluation data.
"""

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from opspilot.modeling import config

# Interactions found in the exploratory analysis (notebook 01, section 6).
INTERACTIONS = [
    ("priority", "hours_until_staffed"),
    ("assigned_team", "team_open_per_agent"),
]


class InteractionTerms(BaseEstimator, TransformerMixin):
    """Numeric x category interaction columns.

    For each (categorical, numeric) pair, adds one column per category seen in
    training: the numeric value where the row has that category, 0 elsewhere.
    A linear model can then give, for example, waiting time a different slope
    for each priority. Categories first seen after fitting get zeros.
    """

    def __init__(self, pairs: list[tuple[str, str]]):
        self.pairs = pairs

    def fit(self, X: pd.DataFrame, y=None):
        self.categories_ = {categorical: sorted(X[categorical].unique()) for categorical, _ in self.pairs}
        return self

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        columns = []
        for categorical, numeric in self.pairs:
            values = X[numeric].to_numpy(dtype=float)
            for category in self.categories_[categorical]:
                columns.append(np.where(X[categorical].to_numpy() == category, values, 0.0))
        return np.column_stack(columns)

    def get_feature_names_out(self, input_features=None) -> np.ndarray:
        return np.array([
            f"{numeric}_x_{categorical}={category}"
            for categorical, numeric in self.pairs
            for category in self.categories_[categorical]
        ], dtype=object)


def linear_preprocessor(interactions: list[tuple[str, str]] | None = None) -> ColumnTransformer:
    """One-hot categories, impute and scale numbers, optionally add interactions.

    Imputation uses the training median plus a missing-value flag. The
    modeling window has no missing values, but a team or subcategory with no
    history in production would.
    """
    numeric = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler())
    transformers = [
        ("categorical", OneHotEncoder(handle_unknown="ignore"), config.CATEGORICAL_FEATURES),
        ("numeric", numeric, config.NUMERIC_FEATURES),
    ]
    if interactions:
        used = sorted({column for pair in interactions for column in pair})
        transformers.append(("interactions", make_pipeline(InteractionTerms(interactions), StandardScaler()), used))
    return ColumnTransformer(transformers, verbose_feature_names_out=True)


def logistic_regression(C: float = 1.0, class_weight: str | None = None,
                        interactions: list[tuple[str, str]] | None = None) -> Pipeline:
    return Pipeline([
        ("preprocess", linear_preprocessor(interactions)),
        ("model", LogisticRegression(C=C, class_weight=class_weight, max_iter=2000)),
    ])


def logistic_regression_grid() -> dict[str, Pipeline]:
    """A small, fixed grid to choose regularization and class weighting on the folds."""
    return {
        f"logreg_C={C}_weight={weight or 'none'}": logistic_regression(C=C, class_weight=weight)
        for C in [0.01, 0.1, 1.0, 10.0]
        for weight in [None, "balanced"]
    }


def coefficient_table(fitted: Pipeline) -> pd.DataFrame:
    """Coefficients of a fitted logistic regression pipeline, largest effect first.

    Numeric inputs are standardized, so their coefficients are per standard
    deviation; one-hot coefficients are relative to the categories' average.
    Correlated features share credit, so a coefficient is not a causal effect.
    """
    names = fitted.named_steps["preprocess"].get_feature_names_out()
    coefficients = fitted.named_steps["model"].coef_[0]
    table = pd.DataFrame({"feature": names, "coefficient": coefficients})
    table["odds_ratio"] = np.exp(table["coefficient"])
    return table.reindex(table["coefficient"].abs().sort_values(ascending=False).index).reset_index(drop=True)
