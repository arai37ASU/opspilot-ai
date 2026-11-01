"""Do embeddings find similar tickets better than keyword matching?

Usage:
    python -m opspilot.ai.similar_eval

Ticket text here comes from templates, so finding the same issue is easy and
embeddings might add nothing. This measures it against TF-IDF, on two tests:

- Real tickets: for tickets in the test period, the share of the nearest
  earlier descriptions that are the same issue. Exact copies of the query are
  left out, because they would score for free.
- Paraphrases: issues written by hand in everyday wording (evals/paraphrases.csv),
  where matching words should help less. The set is small and was written by
  the author of this code, so it is a sanity check rather than a benchmark.

It also reports how the text search's similarity cutoff treats those
paraphrases and some off-topic text (evals/off_topic.csv). The cutoff was chosen
from these same examples, so this shows it is sensible, not that it is validated.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from opspilot.ai.embeddings import EMBEDDING_MODEL, MIN_TEXT_SIMILARITY, embed_texts
from opspilot.modeling.config import RANDOM_SEED, TEST_START

TOP_K = 5
QUERIES = 1000
PARAPHRASES = Path("evals/paraphrases.csv")
OFF_TOPIC = Path("evals/off_topic.csv")


def candidates_and_queries(tickets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Distinct descriptions from before the test period, and a sample of tickets from it."""
    earlier = tickets[tickets["created_at"] < TEST_START]
    candidates = (earlier.groupby("description")["subcategory"].agg(lambda s: s.mode().iloc[0]).reset_index())
    later = tickets[tickets["created_at"] >= TEST_START].drop_duplicates("description")
    return candidates, later.sample(n=min(QUERIES, len(later)), random_state=RANDOM_SEED)


def tfidf_vectors(candidates: list[str], queries: list[str]) -> tuple:
    vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), sublinear_tf=True)
    return vectorizer.fit_transform(candidates), vectorizer.transform(queries)


def embedding_vectors(candidates: list[str], queries: list[str]) -> tuple:
    return normalize(embed_texts(candidates)), normalize(embed_texts(queries))


def nearest(candidate_vectors, query_vectors, exclude: list[np.ndarray] | None = None, k: int = TOP_K) -> np.ndarray:
    """Indices of the k most similar candidates for each query. Vectors are unit length."""
    scores = query_vectors @ candidate_vectors.T
    scores = scores.toarray() if hasattr(scores, "toarray") else np.asarray(scores)
    if exclude is not None:
        for row, positions in enumerate(exclude):
            scores[row, positions] = -np.inf
    return np.argsort(-scores, axis=1)[:, :k]


def scores_for(found: np.ndarray, candidate_labels: np.ndarray, expected: np.ndarray) -> dict:
    hits = candidate_labels[found] == expected[:, None]
    return {"precision_at_5": round(float(hits.mean()), 4),
            "top_1": round(float(hits[:, 0].mean()), 4),
            "any_in_top_5": round(float(hits.any(axis=1).mean()), 4)}


def share_above_cutoff(candidate_vectors, query_vectors) -> float:
    best = np.asarray(query_vectors @ candidate_vectors.T).max(axis=1)
    return round(float((best >= MIN_TEXT_SIMILARITY).mean()), 4)


def evaluate(tickets: pd.DataFrame, paraphrases: pd.DataFrame, off_topic: pd.DataFrame) -> dict:
    candidates, queries = candidates_and_queries(tickets)
    candidate_texts = candidates["description"].tolist()
    position = {text: i for i, text in enumerate(candidate_texts)}
    labels = candidates["subcategory"].to_numpy()
    exclude = [np.array([position[t]]) if t in position else np.array([], dtype=int) for t in queries["description"]]

    results = {"embedding_model": EMBEDDING_MODEL, "candidates": len(candidates), "real_ticket_queries": len(queries),
               "paraphrase_queries": len(paraphrases), "methods": {}}
    for name, vectorize in (("tfidf", tfidf_vectors), ("embeddings", embedding_vectors)):
        text_queries = queries["description"].tolist() + paraphrases["query"].tolist()
        candidate_vectors, query_vectors = vectorize(candidate_texts, text_queries)
        real, handwritten = query_vectors[: len(queries)], query_vectors[len(queries):]
        results["methods"][name] = {
            "real_tickets": scores_for(nearest(candidate_vectors, real, exclude), labels, queries["subcategory"].to_numpy()),
            "paraphrases": scores_for(nearest(candidate_vectors, handwritten), labels, paraphrases["expected"].to_numpy()),
        }
    embedded, handwritten = embedding_vectors(candidate_texts, paraphrases["query"].tolist())
    _, unrelated = embedding_vectors(candidate_texts[:1], off_topic["query"].tolist())
    results["cutoff"] = {"min_similarity": MIN_TEXT_SIMILARITY,
                         "paraphrases_kept": share_above_cutoff(embedded, handwritten),
                         "off_topic_kept": share_above_cutoff(embedded, unrelated)}
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare embeddings with TF-IDF for finding similar tickets.")
    parser.add_argument("--tickets", type=Path, default=Path("data/raw/tickets.csv"))
    parser.add_argument("--output", type=Path, default=Path("reports/ai/similar_tickets.json"))
    args = parser.parse_args()

    tickets = pd.read_csv(args.tickets, usecols=["created_at", "description", "subcategory"], parse_dates=["created_at"])
    results = evaluate(tickets, pd.read_csv(PARAPHRASES), pd.read_csv(OFF_TOPIC))
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
