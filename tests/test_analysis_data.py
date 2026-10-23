import pandas as pd
import pytest

from opspilot.analysis.data import load_features, load_tickets, read_sql

pytestmark = pytest.mark.db


def test_numeric_integer_and_boolean_columns_get_analysis_types(db_conn):
    tickets = load_tickets(db_conn)
    assert tickets["sla_hours"].dtype == "float64"           # NUMERIC, not Decimal objects
    assert tickets["resolution_hours"].dtype == "float64"
    assert tickets["satisfaction_score"].dtype == "Int64"    # nullable integer
    assert tickets["sla_breached"].dtype == "boolean"        # nullable boolean
    assert pd.api.types.is_datetime64_any_dtype(tickets["created_at"])


def test_nulls_survive_conversion(db_conn):
    tickets = load_tickets(db_conn)
    unresolved = tickets["status"] != "resolved"
    assert tickets.loc[unresolved, "sla_breached"].isna().all()
    assert tickets.loc[~unresolved, "sla_breached"].notna().all()


def test_features_load_with_numeric_history_columns(db_conn):
    features = load_features(db_conn)
    assert len(features) == len(load_tickets(db_conn))
    assert features["team_breach_rate_prev_30d"].dtype == "float64"
    assert features["team_open_at_arrival"].dtype == "Int64"


def test_read_sql_accepts_parameters(db_conn):
    result = read_sql(db_conn, "SELECT count(*) AS n FROM tickets WHERE priority = %s", ["P1"])
    assert result["n"].iloc[0] > 0
