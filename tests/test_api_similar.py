"""Similar-ticket search against the test database, with hand-made vectors.

Vectors are written by hand so the expected order is known and the tests need
no model download. The real model is measured by opspilot.ai.similar_eval.
"""

import re
from pathlib import Path

import numpy as np
import pytest

from opspilot.ai.embed_tickets import missing_descriptions, store_embeddings, vector_literal
from opspilot.ai.embeddings import EMBEDDING_DIMENSIONS, MIN_TEXT_SIMILARITY
from opspilot.api import similar
from opspilot.api.similar import outcome_summary

SCHEMA = Path(__file__).resolve().parents[1] / "sql" / "schema" / "003_create_embeddings.sql"


def unit_vector(*weights):
    vector = np.zeros(EMBEDDING_DIMENSIONS)
    vector[:len(weights)] = weights
    return vector / np.linalg.norm(vector)


def test_schema_size_matches_the_embedding_model():
    assert re.search(r"vector\((\d+)\)", SCHEMA.read_text()).group(1) == str(EMBEDDING_DIMENSIONS)


def test_vector_literal_is_pgvector_text():
    assert vector_literal(np.array([0.5, -0.25])) == "[0.5,-0.25]"


def test_outcome_summary_counts_finished_tickets_only():
    tickets = [{"sla_breached": True, "resolution_hours": 10.0}, {"sla_breached": False, "resolution_hours": 20.0},
               {"sla_breached": None, "resolution_hours": None}]
    assert outcome_summary(tickets) == {"resolved": 2, "breached": 1, "median_resolution_hours": 15.0}


def test_outcome_summary_with_nothing_finished():
    assert outcome_summary([]) == {"resolved": 0, "breached": 0, "median_resolution_hours": None}


@pytest.fixture
def embedded(db_conn):
    """Three descriptions of one busy subcategory: the query, a close match and a poor one."""
    rows = db_conn.execute("""
        SELECT description, count(*), max(created_at) FROM tickets
        WHERE subcategory = 'printer_issue' GROUP BY description
        ORDER BY count(*) DESC, description LIMIT 3
    """).fetchall()
    query, close, poor = (row[0] for row in rows)
    vectors = {query: unit_vector(1, 0), close: unit_vector(1, 0.2), poor: unit_vector(0.2, 1)}
    db_conn.execute("DELETE FROM description_embeddings")
    store_embeddings(db_conn, list(vectors), lambda batch: [vectors[text] for text in batch])
    yield {"query": query, "close": close, "poor": poor, "vectors": vectors}
    db_conn.execute("DELETE FROM description_embeddings")


def latest_ticket(db_conn, description):
    return db_conn.execute("SELECT ticket_id, created_at FROM tickets WHERE description = %s "
                           "ORDER BY created_at DESC LIMIT 1", [description]).fetchone()


def test_results_are_ordered_by_similarity(client, db_conn, embedded):
    ticket_id, _ = latest_ticket(db_conn, embedded["query"])
    found = client.get(f"/tickets/{ticket_id}/similar").json()["tickets"]
    assert [t["description"] for t in found] == [embedded["query"], embedded["close"], embedded["poor"]]
    assert found[0]["similarity"] > found[1]["similarity"] > found[2]["similarity"]


def test_nothing_from_the_future_or_the_ticket_itself(client, db_conn, embedded):
    ticket_id, created_at = latest_ticket(db_conn, embedded["query"])
    found = client.get(f"/tickets/{ticket_id}/similar").json()["tickets"]
    assert found and all(t["created_at"] < created_at.isoformat() for t in found)
    assert ticket_id not in {t["ticket_id"] for t in found}


def test_the_earliest_ticket_has_no_earlier_matches(client, db_conn, embedded):
    earliest = db_conn.execute("SELECT ticket_id FROM tickets WHERE description = ANY(%s) ORDER BY created_at LIMIT 1",
                               [list(embedded["vectors"])]).fetchone()[0]
    assert client.get(f"/tickets/{earliest}/similar").json()["tickets"] == []


def test_one_ticket_per_description(client, db_conn, embedded):
    ticket_id, _ = latest_ticket(db_conn, embedded["query"])
    found = client.get(f"/tickets/{ticket_id}/similar", params={"limit": 20}).json()["tickets"]
    assert len({t["description"] for t in found}) == len(found)


def test_unknown_ticket_and_missing_embeddings_are_explained(client, db_conn, embedded):
    assert client.get("/tickets/NOPE/similar").status_code == 404
    other = db_conn.execute("SELECT ticket_id FROM tickets WHERE description <> ALL(%s) LIMIT 1",
                            [list(embedded["vectors"])]).fetchone()[0]
    response = client.get(f"/tickets/{other}/similar")
    assert response.status_code == 503
    assert "embed_tickets" in response.json()["detail"]


def fake_embedding(monkeypatch, vector):
    monkeypatch.setattr(similar, "embed_texts", lambda texts: [vector])


def test_text_search_returns_close_matches(client, embedded, monkeypatch):
    fake_embedding(monkeypatch, unit_vector(1, 0))
    body = client.post("/similar-tickets", json={"text": "the printer jammed"}).json()
    assert embedded["query"] in [t["description"] for t in body["tickets"]]
    assert embedded["poor"] not in [t["description"] for t in body["tickets"]]
    assert all(t["similarity"] >= MIN_TEXT_SIMILARITY for t in body["tickets"])


def test_off_topic_text_returns_nothing(client, embedded, monkeypatch):
    fake_embedding(monkeypatch, unit_vector(0, 0, 1))
    body = client.post("/similar-tickets", json={"text": "what's for lunch"}).json()
    assert body == {"tickets": [], "outcomes": {"resolved": 0, "breached": 0, "median_resolution_hours": None}}


@pytest.mark.parametrize("body", [{"text": "hi"}, {"text": "x" * 501}, {"text": "printer", "limit": 21}])
def test_text_search_rejects_bad_input(client, body):
    assert client.post("/similar-tickets", json=body).status_code == 422


def test_embedding_is_incremental(db_conn, embedded):
    with db_conn.transaction(force_rollback=True):
        waiting = missing_descriptions(db_conn)
        assert embedded["query"] not in waiting
        assert len(waiting) > 0
        store_embeddings(db_conn, waiting[:2], lambda batch: [unit_vector(1)] * len(batch))
        assert len(missing_descriptions(db_conn)) == len(waiting) - 2
