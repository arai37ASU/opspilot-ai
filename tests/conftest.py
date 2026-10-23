import os

import psycopg
import pytest

from opspilot.data_generation.generate import write_dataset
from opspilot.db import connection  # noqa: F401  (loads .env)
from opspilot.db.load import load_dataset


@pytest.fixture(scope="session")
def test_database_url():
    """URL of the test database, or skip when the container is not running."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set (see .env.example)")
    try:
        psycopg.connect(url, connect_timeout=2).close()
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL is not reachable; start it with `docker compose up -d`")
    return url


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory):
    """The default-seed dataset written as CSV to a temporary folder."""
    directory = tmp_path_factory.mktemp("raw")
    write_dataset(directory)
    return directory


@pytest.fixture(scope="session")
def db_conn(test_database_url, data_dir):
    """A connection to the test database with the dataset loaded.

    Tests that change data must do it inside
    `db_conn.transaction(force_rollback=True)` so other tests see the
    original rows.
    """
    with psycopg.connect(test_database_url) as conn:
        load_dataset(conn, data_dir)
        yield conn
