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
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

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


def tree_preprocessor() -> ColumnTransformer:
    """One-hot categories and impute numbers; no scaling, which trees do not need.

    The output is always a sparse matrix. ColumnTransformer otherwise picks
    sparse or dense per batch depending on how many zeros it contains, and
    XGBoost reads zeros that are not stored in a sparse matrix as missing, so
    the same ticket could be scored differently depending on what it was
    batched with. Always sparse keeps training and scoring identical. It also
    means XGBoost treats every zero value as missing and learns a default
    branch for it; that behaviour is what was validated and tested.
    """
    return ColumnTransformer([
        ("categorical", OneHotEncoder(handle_unknown="ignore"), config.CATEGORICAL_FEATURES),
        ("numeric", SimpleImputer(strategy="median", add_indicator=True), config.NUMERIC_FEATURES),
    ], sparse_threshold=1.0, verbose_feature_names_out=True)


def random_forest(min_samples_leaf: int = 1, max_features: str | float = "sqrt", n_estimators: int = 300) -> Pipeline:
    return Pipeline([
        ("preprocess", tree_preprocessor()),
        ("model", RandomForestClassifier(n_estimators=n_estimators, min_samples_leaf=min_samples_leaf,
                                         max_features=max_features, n_jobs=-1, random_state=config.RANDOM_SEED)),
    ])


def xgboost(max_depth: int = 4, learning_rate: float = 0.1, n_estimators: int = 300) -> Pipeline:
    return Pipeline([
        ("preprocess", tree_preprocessor()),
        ("model", XGBClassifier(max_depth=max_depth, learning_rate=learning_rate, n_estimators=n_estimators,
                                subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
                                n_jobs=-1, random_state=config.RANDOM_SEED)),
    ])


def random_forest_grid() -> dict[str, Pipeline]:
    """Leaf size controls how finely trees split; max_features how different the trees are."""
    return {
        f"rf_leaf={leaf}_features={features}": random_forest(min_samples_leaf=leaf, max_features=features)
        for leaf in [1, 5, 20]
        for features in ["sqrt", 0.5]
    }


def xgboost_grid() -> dict[str, Pipeline]:
    """Depth, learning rate and number of trees, with subsampling held at 0.8."""
    return {
        f"xgb_depth={depth}_lr={rate}_trees={trees}": xgboost(max_depth=depth, learning_rate=rate, n_estimators=trees)
        for depth in [3, 5]
        for rate in [0.05, 0.1]
        for trees in [200, 500]
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
