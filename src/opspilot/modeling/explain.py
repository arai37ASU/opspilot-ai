"""Explain the fitted SLA breach model, globally and for individual tickets.

Usage:
    python -m opspilot.modeling.explain

Two methods, because they answer different questions:

- Permutation importance: how much does average precision drop on the test
  tickets when one feature's values are shuffled? Global, model-agnostic,
  and measured in the metric we care about.
- SHAP values: how much did each feature push one ticket's predicted risk up
  or down? They are computed by XGBoost's own TreeSHAP implementation
  (pred_contribs) on exactly the matrix the model predicts from, so they
  match the model's real predictions, including its treatment of zeros in
  sparse input as missing. Values are in log-odds and add up exactly to the
  model's output, so one-hot columns can be summed back into the original
  feature. Gives per-ticket reasons as well as a global ranking.

Neither is causal. Correlated features share credit, and shuffling one of a
correlated pair understates its importance because the other still carries
the information.

Reads the model saved by opspilot.modeling.train. Explaining a model does not
change it, so using test tickets here does not count as reusing the test set
for decisions.
"""

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost
from sklearn.inspection import permutation_importance
from sklearn.pipeline import Pipeline

from opspilot.modeling import config
from opspilot.modeling.dataset import load_modeling_frame, split_train_test, to_model_inputs


def encoded_feature_owners(model: Pipeline) -> list[str]:
    """For each column the preprocessor outputs, the original feature it came from."""
    preprocess = model.named_steps["preprocess"]
    encoder = preprocess.named_transformers_["categorical"]
    owners = [column for column, categories in zip(config.CATEGORICAL_FEATURES, encoder.categories_)
              for _ in categories]
    imputer = preprocess.named_transformers_["numeric"]
    owners += [name.removeprefix("missingindicator_") for name in imputer.get_feature_names_out(config.NUMERIC_FEATURES)]
    if len(owners) != len(preprocess.get_feature_names_out()):
        raise ValueError("encoded columns could not be matched to original features")
    return owners


def shap_by_feature(model: Pipeline, X: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """SHAP values summed per original feature (log-odds), and the base value.

    For every ticket, base value + row sum equals the model's log-odds output.
    The matrix is passed to XGBoost unchanged; converting it to dense first
    would turn zeros the model reads as missing into real zeros and explain a
    different model.
    """
    encoded = model.named_steps["preprocess"].transform(X)
    booster = model.named_steps["model"].get_booster()
    contributions = booster.predict(xgboost.DMatrix(encoded), pred_contribs=True)
    values = pd.DataFrame(contributions[:, :-1], index=X.index, columns=encoded_feature_owners(model))
    grouped = values.T.groupby(level=0, sort=False).sum().T
    return grouped[config.FEATURES], float(contributions[0, -1])  # last column is the bias


def shap_importance(grouped: pd.DataFrame) -> pd.DataFrame:
    """Global ranking: mean absolute SHAP value per feature."""
    importance = grouped.abs().mean().sort_values(ascending=False)
    return pd.DataFrame({"feature": importance.index, "mean_abs_shap": importance.values})


def permutation_importance_table(model: Pipeline, X: pd.DataFrame, y: pd.Series,
                                 n_repeats: int = 5) -> pd.DataFrame:
    result = permutation_importance(model, X, y, scoring="average_precision", n_repeats=n_repeats,
                                    random_state=config.RANDOM_SEED, n_jobs=1)
    table = pd.DataFrame({"feature": X.columns, "ap_drop_mean": result.importances_mean,
                          "ap_drop_std": result.importances_std})
    return table.sort_values("ap_drop_mean", ascending=False).reset_index(drop=True)


def ticket_reasons(grouped_row: pd.Series, feature_row: pd.Series, top: int = 3) -> list[dict]:
    """The features that pushed one ticket's risk furthest, with their values.

    Positive contributions raise the risk, negative ones lower it.
    """
    order = grouped_row.abs().sort_values(ascending=False).index[:top]
    return [{"feature": f, "value": _plain(feature_row[f]), "contribution": round(float(grouped_row[f]), 3)}
            for f in order]


def _plain(value):
    return value.item() if hasattr(value, "item") else value


def example_tickets(test: pd.DataFrame, scores: np.ndarray, threshold: float) -> dict[str, int]:
    """One position each for a caught breach, a false alarm, and a missed breach (the most confident of each)."""
    y = test[config.TARGET].astype(bool).to_numpy()
    flagged = scores >= threshold
    cases = {
        "caught_breach": np.flatnonzero(flagged & y),
        "false_alarm": np.flatnonzero(flagged & ~y),
        "missed_breach": np.flatnonzero(~flagged & y),
    }
    pick = {"caught_breach": np.argmax, "false_alarm": np.argmax, "missed_breach": np.argmin}
    return {name: int(positions[pick[name](scores[positions])]) for name, positions in cases.items() if len(positions)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Explain the fitted SLA breach model.")
    parser.add_argument("--models-dir", type=Path, default=Path("models"))
    parser.add_argument("--reports-dir", type=Path, default=Path("reports/modeling"))
    args = parser.parse_args()

    model = joblib.load(args.models_dir / "sla_breach_model.joblib")
    threshold = json.loads((args.models_dir / "sla_breach_model.json").read_text())["threshold"]
    _, test = split_train_test(load_modeling_frame())
    X, y = to_model_inputs(test)
    scores = model.predict_proba(X)[:, 1]

    grouped, base_value = shap_by_feature(model, X)
    importance = shap_importance(grouped).merge(permutation_importance_table(model, X, y), on="feature")
    importance.round(4).to_csv(args.reports_dir / "feature_importance.csv", index=False)

    examples = {}
    for case, position in example_tickets(test, scores, threshold).items():
        examples[case] = {
            "ticket_id": test["ticket_id"].iloc[position],
            "predicted_risk": round(float(scores[position]), 3),
            "breached": bool(y.iloc[position]),
            "reasons": ticket_reasons(grouped.iloc[position], X.iloc[position], top=4),
        }
    (args.reports_dir / "example_explanations.json").write_text(
        json.dumps({"base_log_odds": round(base_value, 3), "threshold": threshold, "examples": examples}, indent=2) + "\n")

    with pd.option_context("display.width", 120):
        print(importance.round(4).to_string(index=False))
    print(json.dumps(examples, indent=2))


if __name__ == "__main__":
    main()
