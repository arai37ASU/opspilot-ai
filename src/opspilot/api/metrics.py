"""Verified operational metrics, served as JSON.

Two kinds of endpoint:

- Typed KPI endpoints (overview, teams, trend) with date filters, backed by
  sql/api/metrics.sql, for the dashboard.
- A catalog that serves any query in sql/analysis by name, so other clients
  (such as the AI layer) can fetch numbers computed in the database instead
  of producing their own.
"""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import psycopg
from fastapi import APIRouter, HTTPException, Query, Request

from opspilot.analysis.data import read_sql
from opspilot.api.schemas import AnalysisQuery, AnalysisResult, DayPoint, MonthPoint, Overview, Spikes, Teams
from opspilot.db.analysis import analysis_queries
from opspilot.db.sql_files import parse_named_queries

SQL_DIR = Path(__file__).resolve().parents[3] / "sql"
METRICS_SQL = {query.name: query.sql for query in parse_named_queries((SQL_DIR / "api" / "metrics.sql").read_text())}
ANALYSIS = {stem: {query.name: query for query in queries} for stem, queries in analysis_queries().items()}

# Spike days of one issue less than this far apart belong to the same episode.
EPISODE_GAP = timedelta(days=7)


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


def period_overview(conn: psycopg.Connection, start: date, end: date) -> dict:
    params = {"start": start, "end": end}
    totals = records(read_sql(conn, METRICS_SQL["overview"], params))[0]
    by_priority = records(read_sql(conn, METRICS_SQL["by_priority"], params))
    return {"start": start, "end": end, **totals, "by_priority": by_priority}


def period_teams(conn: psycopg.Connection, start: date, end: date) -> list[dict]:
    return records(read_sql(conn, METRICS_SQL["by_team"], {"start": start, "end": end}))


def all_spikes(conn: psycopg.Connection) -> tuple[list[dict], list[dict]]:
    query = ANALYSIS["08_recurring_issue_spikes"]["daily_spikes"]
    return group_spikes(records(read_sql(conn, query.sql)))


@router.get("/overview", response_model=Overview)
def overview(request: Request, start: date | None = Query(None, description="First creation date, inclusive"),
             end: date | None = Query(None, description="Last creation date, inclusive")):
    """Headline KPIs for tickets created in the date range (default: all data)."""
    with request.app.state.pool.connection() as conn:
        start, end = date_range(conn, start, end)
        return period_overview(conn, start, end)


@router.get("/teams", response_model=Teams)
def teams(request: Request, start: date | None = Query(None), end: date | None = Query(None)):
    """Per-team volume, breach rate, resolution time and misrouting for the date range."""
    with request.app.state.pool.connection() as conn:
        start, end = date_range(conn, start, end)
        return {"start": start, "end": end, "teams": period_teams(conn, start, end)}


@router.get("/daily", response_model=list[DayPoint])
def daily(request: Request, start: date | None = Query(None), end: date | None = Query(None)):
    """Ticket volume and breach rate for every day in the range, including days with no tickets."""
    with request.app.state.pool.connection() as conn:
        start, end = date_range(conn, start, end)
        return records(read_sql(conn, METRICS_SQL["daily"], {"start": start, "end": end}))


@router.get("/trend", response_model=list[MonthPoint])
def trend(request: Request, start: date | None = Query(None), end: date | None = Query(None)):
    """Monthly ticket volume and breach rate for the date range (default: all data).

    Months cut by the range count only the days inside it.
    """
    with request.app.state.pool.connection() as conn:
        start, end = date_range(conn, start, end)
        return records(read_sql(conn, METRICS_SQL["monthly_trend"], {"start": start, "end": end}))


def group_spikes(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Label each spike day and group the days into episodes.

    Days of one issue up to EPISODE_GAP apart form an episode. An issue with
    a single episode is "one_off", a suspected incident; an issue that comes
    back is "recurring", such as password resets every semester. This uses
    ticket data only, so it has blind spots: two outages of the same kind
    would count as recurring, and a seasonal surge looks one-off the first
    time it happens.
    """
    episodes = []
    for row in sorted(rows, key=lambda r: (r["subcategory"], r["day"])):
        latest = episodes[-1] if episodes else None
        if latest and latest["subcategory"] == row["subcategory"] and row["day"] - latest["end"] <= EPISODE_GAP:
            latest["end"] = row["day"]
            latest["tickets"] += row["tickets"]
            latest["peak_two_hours"] = max(latest["peak_two_hours"], row["peak_two_hours"])
        else:
            episodes.append({"subcategory": row["subcategory"], "start": row["day"], "end": row["day"],
                             "tickets": row["tickets"], "typical_daily": row["typical_daily"],
                             "peak_two_hours": row["peak_two_hours"]})

    counts = pd.Series([episode["subcategory"] for episode in episodes]).value_counts()
    kind = lambda subcategory: "one_off" if counts[subcategory] == 1 else "recurring"
    labelled_days = [{**row, "kind": kind(row["subcategory"])} for row in rows]
    labelled_episodes = [{**episode, "kind": kind(episode["subcategory"])}
                         for episode in sorted(episodes, key=lambda e: e["start"])]
    return labelled_days, labelled_episodes


@router.get("/spikes", response_model=Spikes)
def spikes(request: Request):
    """Unusual bursts of one issue, by day and grouped into episodes.

    One-off episodes are suspected incidents, inferred from ticket data alone.
    """
    with request.app.state.pool.connection() as conn:
        days, episodes = all_spikes(conn)
    return {"days": days, "episodes": episodes}


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
