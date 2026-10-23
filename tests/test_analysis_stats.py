import numpy as np
import pandas as pd
import pytest

from opspilot.analysis.stats import (
    cramers_v,
    difference_interval,
    population_stability_index,
    rank_auc,
    standardized_rates,
    wilson_interval,
    z_value,
)

scipy_stats = pytest.importorskip("scipy.stats")


def test_z_value_for_common_confidence_levels():
    assert z_value(0.95) == pytest.approx(1.959964, abs=1e-6)
    assert z_value(0.90) == pytest.approx(1.644854, abs=1e-6)


@pytest.mark.parametrize(
    "successes, n, expected",
    [
        (5, 10, (0.2366, 0.7634)),   # worked by hand from the Wilson formula
        (0, 10, (0.0, 0.2775)),      # stays above 0 width even at 0%
        (10, 10, (0.7225, 1.0)),
    ],
)
def test_wilson_interval_known_values(successes, n, expected):
    assert wilson_interval(successes, n) == pytest.approx(expected, abs=1e-4)


def test_wilson_interval_matches_scipy():
    result = scipy_stats.binomtest(37, 240).proportion_ci(confidence_level=0.95, method="wilson")
    assert wilson_interval(37, 240) == pytest.approx((result.low, result.high), abs=1e-9)


def test_wilson_interval_narrows_with_more_data():
    small = wilson_interval(15, 100)
    large = wilson_interval(1500, 10_000)
    assert large[1] - large[0] < small[1] - small[0]


def test_wilson_interval_rejects_impossible_counts():
    with pytest.raises(ValueError):
        wilson_interval(11, 10)
    with pytest.raises(ValueError):
        wilson_interval(0, 0)


def test_difference_interval_by_hand():
    # p_a = 0.3, p_b = 0.2, se = sqrt(0.21/100 + 0.16/100) = 0.0608
    difference, low, high = difference_interval(30, 100, 20, 100)
    assert difference == pytest.approx(0.10)
    assert high - difference == pytest.approx(1.959964 * np.sqrt(0.0037), abs=1e-6)
    assert low < difference < high


def test_standardization_removes_a_pure_mix_effect():
    """Two groups with identical rates within each stratum but different mixes."""
    rows = (
        [("A", "easy", 0)] * 90 + [("A", "easy", 1)] * 10      # A: mostly easy, 10% within easy
        + [("A", "hard", 0)] * 5 + [("A", "hard", 1)] * 5      # 50% within hard
        + [("B", "easy", 0)] * 9 + [("B", "easy", 1)] * 1
        + [("B", "hard", 0)] * 45 + [("B", "hard", 1)] * 45
    )
    frame = pd.DataFrame(rows, columns=["group", "stratum", "outcome"])
    result = standardized_rates(frame, "group", "stratum", "outcome")

    assert result.loc["A", "crude_rate"] < result.loc["B", "crude_rate"]
    assert result.loc["A", "adjusted_rate"] == pytest.approx(result.loc["B", "adjusted_rate"])


def test_standardization_gives_nan_when_a_group_misses_a_stratum():
    frame = pd.DataFrame({
        "group": ["A", "A", "B"],
        "stratum": ["x", "y", "x"],
        "outcome": [1, 0, 1],
    })
    result = standardized_rates(frame, "group", "stratum", "outcome")
    assert np.isnan(result.loc["B", "adjusted_rate"])
    assert not np.isnan(result.loc["A", "adjusted_rate"])


def test_cramers_v_matches_scipy():
    table = np.array([[120, 80, 40], [60, 90, 110]])
    expected = scipy_stats.contingency.association(table, method="cramer", correction=False)
    assert cramers_v(table) == pytest.approx(expected)


def test_cramers_v_extremes():
    assert cramers_v(np.array([[50, 0], [0, 50]])) == pytest.approx(1.0)
    assert cramers_v(np.array([[25, 25], [25, 25]])) == pytest.approx(0.0)


def test_rank_auc_matches_counting_every_pair():
    rng = np.random.default_rng(1)
    scores = rng.integers(0, 5, size=300).astype(float)  # many ties on purpose
    labels = rng.random(300) < 0.3
    positives, negatives = scores[labels], scores[~labels]
    wins = (positives[:, None] > negatives[None, :]).sum() + 0.5 * (positives[:, None] == negatives[None, :]).sum()
    assert rank_auc(scores, labels) == pytest.approx(wins / (len(positives) * len(negatives)))


def test_rank_auc_extremes_and_missing_scores():
    labels = [False, False, True, True]
    assert rank_auc([1, 2, 3, 4], labels) == 1.0
    assert rank_auc([4, 3, 2, 1], labels) == 0.0
    assert rank_auc(pd.array([1, None, 3, 4], dtype="Int64"), labels) == 1.0
    with pytest.raises(ValueError):
        rank_auc([1, 2], [True, True])


def test_psi_is_near_zero_for_the_same_distribution():
    rng = np.random.default_rng(0)
    a = pd.Series(rng.normal(size=20_000))
    b = pd.Series(rng.normal(size=20_000))
    assert population_stability_index(a, b) < 0.01


def test_psi_flags_a_large_shift():
    rng = np.random.default_rng(0)
    a = pd.Series(rng.normal(size=20_000))
    b = pd.Series(rng.normal(loc=1.0, size=20_000))
    assert population_stability_index(a, b) > 0.25


def test_psi_handles_categories_including_new_ones():
    before = pd.Series(["a"] * 50 + ["b"] * 50)
    same = pd.Series(["a"] * 50 + ["b"] * 50)
    shifted = pd.Series(["a"] * 20 + ["b"] * 50 + ["c"] * 30)
    assert population_stability_index(before, same) == pytest.approx(0.0)
    assert population_stability_index(before, shifted) > 0.25
