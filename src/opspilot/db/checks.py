"""Run the data-quality checks in sql/checks/data_quality.sql.

Usage:
    python -m opspilot.db.checks

Exits with status 1 when any error-severity check finds rows, so the same
command can gate a pipeline or CI job later.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

from opspilot.db.connection import connect
from opspilot.db.sql_files import parse_named_queries

CHECKS_FILE = Path(__file__).resolve().parents[3] / "sql" / "checks" / "data_quality.sql"
SEVERITIES = {"error", "warning"}
SAMPLE_SIZE = 3


@dataclass(frozen=True)
class Check:
    name: str
    severity: str
    query: str


@dataclass(frozen=True)
class CheckResult:
    check: Check
    row_count: int
    sample: list[tuple]

    @property
    def passed(self) -> bool:
        return self.row_count == 0


def parse_checks(text: str) -> list[Check]:
    """Named queries whose first comment line is `severity: error|warning`."""
    checks = []
    for query in parse_named_queries(text):
        severity_match = re.fullmatch(r"severity:\s*(\w+)", query.comments[0]) if query.comments else None
        if not severity_match or severity_match.group(1) not in SEVERITIES:
            raise ValueError(f"check {query.name!r} needs a '-- severity:' line with one of {sorted(SEVERITIES)}")
        checks.append(Check(query.name, severity_match.group(1), query.sql))
    return checks


def load_checks(path: Path = CHECKS_FILE) -> list[Check]:
    return parse_checks(path.read_text())


def run_check(conn: psycopg.Connection, check: Check) -> CheckResult:
    rows = conn.execute(check.query).fetchall()
    return CheckResult(check, len(rows), rows[:SAMPLE_SIZE])


def run_checks(conn: psycopg.Connection, checks: list[Check] | None = None) -> list[CheckResult]:
    return [run_check(conn, check) for check in checks or load_checks()]


def format_results(results: list[CheckResult]) -> str:
    lines = []
    for result in results:
        if result.passed:
            label = "PASS"
        else:
            label = "FAIL" if result.check.severity == "error" else "WARN"
        line = f"{label}  {result.check.severity:8} {result.check.name:32} {result.row_count:>6} rows"
        lines.append(line)
        for row in result.sample if not result.passed else []:
            lines.append(f"        e.g. {row}")
    return "\n".join(lines)


def main() -> None:
    with connect() as conn:
        results = run_checks(conn)
    print(format_results(results))
    if any(not r.passed and r.check.severity == "error" for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
