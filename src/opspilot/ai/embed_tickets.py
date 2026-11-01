"""Embed every ticket description not yet in the database.

Usage:
    python -m opspilot.ai.embed_tickets

Safe to rerun: descriptions that already have an embedding are skipped.
"""

import argparse

import psycopg

from opspilot.ai.embeddings import embed_texts
from opspilot.db.connection import connect

BATCH_SIZE = 512


def vector_literal(vector) -> str:
    """pgvector's text form. Enough precision to keep the stored vector unit length."""
    return "[" + ",".join(f"{value:.7g}" for value in vector) + "]"


def missing_descriptions(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute("""
        SELECT DISTINCT t.description
        FROM tickets AS t
        LEFT JOIN description_embeddings AS e USING (description)
        WHERE e.description IS NULL
        ORDER BY t.description
    """).fetchall()
    return [row[0] for row in rows]


def store_embeddings(conn: psycopg.Connection, texts: list[str], embed=embed_texts) -> int:
    """Embed and save `texts` in batches, committing each one."""
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        rows = [(text, vector_literal(vector)) for text, vector in zip(batch, embed(batch))]
        with conn.transaction(), conn.cursor() as cursor:
            cursor.executemany("INSERT INTO description_embeddings (description, embedding) VALUES (%s, %s::vector)", rows)
    return len(texts)


def main() -> None:
    argparse.ArgumentParser(description="Embed ticket descriptions not yet in the database.").parse_args()
    with connect() as conn:
        conn.autocommit = True
        added = store_embeddings(conn, missing_descriptions(conn))
        total = conn.execute("SELECT count(*) FROM description_embeddings").fetchone()[0]
    print(f"added {added:,} embeddings; {total:,} descriptions are embedded")


if __name__ == "__main__":
    main()
