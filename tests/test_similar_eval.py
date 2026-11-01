"""The evaluation's own logic: a broken evaluation would report a false result."""

import numpy as np
import pandas as pd

from opspilot.ai.similar_eval import candidates_and_queries, nearest, scores_for
from opspilot.modeling.config import TEST_START


def test_candidates_never_come_from_the_test_period():
    tickets = pd.DataFrame({
        "created_at": [TEST_START - pd.Timedelta(days=1), TEST_START, TEST_START + pd.Timedelta(days=1)],
        "description": ["before", "after one", "after two"], "subcategory": ["a", "b", "c"],
    })
    candidates, queries = candidates_and_queries(tickets)
    assert candidates["description"].tolist() == ["before"]
    assert set(queries["description"]) == {"after one", "after two"}


def test_excluded_candidates_are_not_returned():
    candidates = np.eye(3)
    query = np.array([[1.0, 0.5, 0.1]])
    assert nearest(candidates, query, k=2).tolist() == [[0, 1]]
    assert nearest(candidates, query, [np.array([0])], k=2).tolist() == [[1, 2]]


def test_scores():
    labels = np.array(["a", "b", "a"])
    found = np.array([[0, 1], [1, 2]])
    assert scores_for(found, labels, np.array(["a", "a"])) == {"precision_at_5": 0.5, "top_1": 0.5, "any_in_top_5": 1.0}
