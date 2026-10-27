import json
import os
from pathlib import Path

import joblib
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

    Autocommit, so reads never leave a transaction open (which would hold
    locks other sessions, such as a notebook kernel, have to wait for), and
    `conn.transaction()` starts a real transaction rather than a savepoint.

    Tests that change data must do it inside
    `db_conn.transaction(force_rollback=True)` so other tests see the
    original rows.
    """
    with psycopg.connect(test_database_url, autocommit=True) as conn:
        load_dataset(conn, data_dir)
        yield conn


@pytest.fixture(scope="session")
def api_model_dir(tmp_path_factory, db_conn):
    """A small XGBoost model and its metadata, so API tests do not depend on models/."""
    from opspilot.modeling.dataset import load_modeling_frame, split_train_test, to_model_inputs
    from opspilot.modeling.pipelines import xgboost

    directory = tmp_path_factory.mktemp("models")
    train, _ = split_train_test(load_modeling_frame(db_conn))
    X, y = to_model_inputs(train.head(5000))
    joblib.dump(xgboost(n_estimators=20).fit(X, y), directory / "sla_breach_model.joblib")
    (directory / "sla_breach_model.json").write_text(json.dumps({
        "model": "xgboost", "threshold": 0.457, "features": list(X.columns),
        "train_period": ["2024-02-01", "2025-06-30"], "git": {"commit": "a" * 40},
    }))
    return directory


@pytest.fixture(scope="session")
def client(api_model_dir, test_database_url):
    """An API client against the test database. The with block runs startup and shutdown."""
    from fastapi.testclient import TestClient

    from opspilot.api.main import create_app
    from opspilot.api.settings import Settings

    settings = Settings(database_url=test_database_url, model_dir=api_model_dir,
                        reports_dir=Path("reports/modeling"))
    with TestClient(create_app(settings)) as client:
        yield client
