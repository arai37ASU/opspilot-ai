"""Small statistical helpers used in the exploratory analysis.

Each is a few lines of arithmetic, written out rather than imported so the
method is visible and testable. Tests compare them with SciPy where SciPy has
an equivalent.
"""

from statistics import NormalDist

import numpy as np
import pandas as pd


def z_value(confidence: float) -> float:
    """Two-sided critical value, for example 1.96 for 95%."""
    return NormalDist().inv_cdf(0.5 + confidence / 2)


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Confidence interval for a proportion.

    Preferred over the textbook p +/- z * sqrt(p(1-p)/n) because that interval
    collapses to zero width at 0% or 100% and can extend below 0 or above 1
    for small groups. Wilson stays inside [0, 1] and behaves well at the edges.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= successes <= n:
        raise ValueError("successes must be between 0 and n")
    z = z_value(confidence)
    p = successes / n
    denominator = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denominator
    half_width = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denominator
    return max(0.0, centre - half_width), min(1.0, centre + half_width)


def difference_interval(
    successes_a: int, n_a: int, successes_b: int, n_b: int, confidence: float = 0.95
) -> tuple[float, float, float]:
    """Difference between two proportions (a - b) with a normal-approximation interval.

    Returns (difference, low, high). Fine for the group sizes in this project
    (hundreds or more per group); for very small groups a method such as
    Newcombe's would be safer.
    """
    p_a, p_b = successes_a / n_a, successes_b / n_b
    standard_error = np.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    difference = p_a - p_b
    margin = z_value(confidence) * standard_error
    return difference, difference - margin, difference + margin


def standardized_rates(frame: pd.DataFrame, group: str, stratum: str, outcome: str) -> pd.DataFrame:
    """Crude and directly standardized outcome rates per group.

    The adjusted rate answers: what would this group's rate be if it had the
    same mix of strata as the data overall? If adjusted rates are much closer
    together than crude rates, the crude differences were mostly due to mix.

    A group missing any stratum gets NaN, because its rate in that stratum is
    unknown and filling it in would be a guess.
    """
    weights = frame[stratum].value_counts(normalize=True)
    rates = frame.groupby([group, stratum])[outcome].mean().unstack(stratum).reindex(columns=weights.index)

    result = pd.DataFrame({
        "n": frame.groupby(group).size(),
        "crude_rate": frame.groupby(group)[outcome].mean(),
        "adjusted_rate": (rates * weights).sum(axis=1, min_count=len(weights)),
    })
    result.loc[rates.isna().any(axis=1), "adjusted_rate"] = np.nan
    return result


def cramers_v(table: pd.DataFrame | np.ndarray) -> float:
    """Strength of association in a contingency table, from 0 (none) to 1.

    Unlike a chi-square p-value it does not grow with sample size, so it shows
    whether an association is large, not just whether it exists.
    """
    observed = np.asarray(table, dtype=float)
    n = observed.sum()
    expected = observed.sum(axis=1, keepdims=True) * observed.sum(axis=0, keepdims=True) / n
    chi_square = ((observed - expected) ** 2 / expected).sum()
    return float(np.sqrt(chi_square / (n * (min(observed.shape) - 1))))


def rank_auc(scores, labels) -> float:
    """ROC-AUC of a single score, computed from ranks.

    It is the probability that a randomly chosen positive scores higher than a
    randomly chosen negative, with ties counted as half. 0.5 means no signal;
    values below 0.5 mean the signal runs in the opposite direction. Rows with
    a missing score are ignored.
    """
    scores = pd.Series(scores).astype("float64").to_numpy()
    labels = pd.Series(labels).astype(bool).to_numpy()
    keep = ~np.isnan(scores)
    scores, labels = scores[keep], labels[keep]

    n_positive = labels.sum()
    n_negative = len(labels) - n_positive
    if n_positive == 0 or n_negative == 0:
        raise ValueError("need at least one positive and one negative")
    ranks = pd.Series(scores).rank(method="average").to_numpy()
    return float((ranks[labels].sum() - n_positive * (n_positive + 1) / 2) / (n_positive * n_negative))


def population_stability_index(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    """How much a variable's distribution shifted between two samples.

    Numeric variables are cut into bins at the expected sample's quantiles;
    other variables use their categories. Common reading in model monitoring:
    below 0.1 stable, 0.1 to 0.25 moderate shift, above 0.25 large shift.
    """
    expected, actual = expected.dropna(), actual.dropna()
    if pd.api.types.is_numeric_dtype(expected) and not pd.api.types.is_bool_dtype(expected):
        edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
        edges[0], edges[-1] = -np.inf, np.inf
        expected_share = pd.cut(expected, edges).value_counts(normalize=True, sort=False)
        actual_share = pd.cut(actual, edges).value_counts(normalize=True, sort=False)
    else:
        categories = sorted(set(expected) | set(actual), key=str)
        expected_share = expected.value_counts(normalize=True).reindex(categories, fill_value=0)
        actual_share = actual.value_counts(normalize=True).reindex(categories, fill_value=0)

    # An empty bin would make the log undefined; a tiny floor keeps it finite.
    e = np.clip(expected_share.to_numpy(), 1e-4, None)
    a = np.clip(actual_share.to_numpy(), 1e-4, None)
    return float(np.sum((a - e) * np.log(a / e)))
