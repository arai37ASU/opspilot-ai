"""Verified operational metrics, served as JSON.

Two kinds of endpoint:

- Typed KPI endpoints (overview, teams, trend) with date filters, backed by
  sql/api/metrics.sql, for the dashboard.
- A catalog that serves any query in sql/analysis by name, so other clients
  (such as the AI layer) can fetch numbers computed in the database instead
  of producing their own.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import psycopg
from fastapi import APIRouter, HTTPException, Query, Request

from opspilot.analysis.data import read_sql
from opspilot.api.schemas import AnalysisQuery, AnalysisResult, MonthPoint, Overview, Teams
from opspilot.db.analysis import analysis_queries
from opspilot.db.sql_files import parse_named_queries

SQL_DIR = Path(__file__).resolve().parents[3] / "sql"
METRICS_SQL = {query.name: query.sql for query in parse_named_queries((SQL_DIR / "api" / "metrics.sql").read_text())}
ANALYSIS = {stem: {query.name: query for query in queries} for stem, queries in analysis_queries().items()}


def file_question(stem: str) -> str:
    """The question an analysis file answers: its opening comment line."""
    for line in (SQL_DIR / "analysis" / f"{stem}.sql").read_text().splitlines():
        if line.startswith("--") and line.strip("- "):
            return line.lstrip("- ").strip()
    return ""

router = APIRouter(prefix="/metrics", tags=["metrics"])


def records(frame: pd.DataFrame) -> list[dict]:
    """Rows as JSON-ready dicts: missing values become None."""
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def date_range(conn: psycopg.Connection, start: date | None, end: date | None) -> tuple[date, date]:
    """Fill in missing bounds with the calendar's first and last day, and check the order."""
    first, last = conn.execute("SELECT min(day), max(day) FROM calendar_days").fetchone()
    start, end = start or first, end or last
    if start > end:
        raise HTTPException(status_code=422, detail=f"start {start} is after end {end}")
    return start, end


@router.get("/overview", response_model=Overview)
def overview(request: Request, start: date | None = Query(None, description="First creation date, inclusive"),
             end: date | None = Query(None, description="Last creation date, inclusive")):
    """Headline KPIs for tickets created in the date range (default: all data)."""
    with request.app.state.pool.connection() as conn:
        start, end = date_range(conn, start, end)
        params = {"start": start, "end": end}
        totals = records(read_sql(conn, METRICS_SQL["overview"], params))[0]
        by_priority = records(read_sql(conn, METRICS_SQL["by_priority"], params))
    return {"start": start, "end": end, **totals, "by_priority": by_priority}


@router.get("/teams", response_model=Teams)
def teams(request: Request, start: date | None = Query(None), end: date | None = Query(None)):
    """Per-team volume, breach rate, resolution time and misrouting for the date range."""
    with request.app.state.pool.connection() as conn:
        start, end = date_range(conn, start, end)
        rows = records(read_sql(conn, METRICS_SQL["by_team"], {"start": start, "end": end}))
    return {"start": start, "end": end, "teams": rows}


@router.get("/trend", response_model=list[MonthPoint])
def trend(request: Request):
    """Monthly ticket volume and breach rate across the whole dataset."""
    with request.app.state.pool.connection() as conn:
        return records(read_sql(conn, METRICS_SQL["monthly_trend"]))


@router.get("/analysis", response_model=list[AnalysisQuery])
def analysis_catalog():
    """Every saved analysis query, with its description, that /metrics/analysis/{file}/{query} can run."""
    return [
        {"file": stem, "query": name,
         "description": " ".join([file_question(stem), *query.comments]).strip(),
         "path": f"/metrics/analysis/{stem}/{name}"}
        for stem, queries in ANALYSIS.items() for name, query in queries.items()
    ]


@router.get("/analysis/{file}/{query}", response_model=AnalysisResult,
            responses={404: {"description": "No such analysis query"}})
def run_analysis_query(file: str, query: str, request: Request):
    """Run one analysis query from sql/analysis and return its rows."""
    named = ANALYSIS.get(file, {}).get(query)
    if named is None:
        raise HTTPException(status_code=404, detail=f"no analysis query {file}/{query}; see /metrics/analysis")
    with request.app.state.pool.connection() as conn:
        rows = records(read_sql(conn, named.sql))
    return {"file": file, "query": query, "rows": rows}
