import os

import psycopg
import pytest

pytestmark = pytest.mark.db


def test_can_query_the_test_database(test_database_url):
    with psycopg.connect(test_database_url) as conn:
        version = conn.execute("SHOW server_version").fetchone()[0]
        database = conn.execute("SELECT current_database()").fetchone()[0]
    assert version.startswith("17")
    assert database == "opspilot_test"


def test_test_database_is_separate_from_analysis_database(test_database_url):
    # Tests truncate and reload tables, so they must never point at the main database.
    assert test_database_url != os.environ.get("DATABASE_URL")
