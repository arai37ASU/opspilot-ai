"""Tests for the data-quality checks.

Parser and formatting tests run without a database. The rest prove each check
is quiet on clean data and fires when its problem is planted, inside a
transaction that is always rolled back.
"""

import pytest

from opspilot.db.checks import Check, CheckResult, format_results, load_checks, parse_checks, run_check

CHECKS = {check.name: check for check in load_checks()}

RESOLVED = "SELECT ticket_id FROM tickets WHERE status = 'resolved'"


def test_checks_file_parses_with_unique_names_and_severities():
    assert len(CHECKS) >= 10
    assert {check.severity for check in CHECKS.values()} == {"error", "warning"}


def test_parser_requires_a_severity():
    with pytest.raises(ValueError, match="severity"):
        parse_checks("-- name: no_severity\nSELECT 1;\n")


def test_parser_rejects_duplicate_names():
    text = "-- name: same\n-- severity: error\nSELECT 1;\n\n-- name: same\n-- severity: error\nSELECT 2;\n"
    with pytest.raises(ValueError, match="duplicate"):
        parse_checks(text)


def test_parser_strips_comments_and_trailing_semicolon():
    [check] = parse_checks("-- name: one\n-- severity: warning\n-- why it matters\nSELECT 1;\n")
    assert check == Check("one", "warning", "SELECT 1")


def test_format_labels_failures_by_severity():
    results = [
        CheckResult(Check("clean", "error", "SELECT 1"), 0, []),
        CheckResult(Check("broken", "error", "SELECT 1"), 2, [("a",), ("b",)]),
        CheckResult(Check("odd", "warning", "SELECT 1"), 1, [("c",)]),
    ]
    lines = format_results(results).splitlines()
    assert lines[0].startswith("PASS")
    assert lines[1].startswith("FAIL")
    assert any(line.startswith("WARN") for line in lines)


# --- Against the loaded test database ---------------------------------------------


@pytest.mark.db
def test_error_checks_pass_on_generated_data(db_conn):
    for check in CHECKS.values():
        if check.severity == "error":
            assert run_check(db_conn, check).passed, check.name


PLANTED_PROBLEMS = {
    "sla_due_at_matches_sla_hours":
        f"UPDATE tickets SET sla_due_at = sla_due_at + INTERVAL '1 hour' WHERE ticket_id = ({RESOLVED} LIMIT 1)",
    "resolution_hours_match_timestamps":
        "UPDATE tickets SET resolution_hours = resolution_hours + 0.5 WHERE ticket_id = "
        f"({RESOLVED} AND resolution_hours < sla_hours - 1 LIMIT 1)",
    "sla_hours_match_policy":
        "UPDATE tickets SET sla_hours = sla_hours + 1, sla_due_at = sla_due_at + INTERVAL '1 hour' "
        f"WHERE ticket_id = ({RESOLVED} AND NOT sla_breached LIMIT 1)",
    "created_within_calendar":
        f"UPDATE tickets SET created_at = created_at - INTERVAL '400 days' WHERE ticket_id = ({RESOLVED} LIMIT 1)",
    "resolved_before_snapshot":
        f"UPDATE tickets SET resolved_at = '2026-01-05' WHERE ticket_id = ({RESOLVED} LIMIT 1)",
    "team_change_has_reassignment":
        "UPDATE tickets SET reassignment_count = 0 WHERE ticket_id = "
        f"({RESOLVED} AND resolved_by_team <> assigned_team LIMIT 1)",
    "blank_description":
        "UPDATE tickets SET description = '   ' WHERE ticket_id = 'TKT-000001'",
    "unexpected_department":
        "UPDATE tickets SET department = 'engineering' WHERE ticket_id = 'TKT-000001'",
    "resolved_outside_owning_team":
        "UPDATE tickets SET resolved_by_team = 'Service Desk', reassignment_count = 1 WHERE ticket_id = "
        f"({RESOLVED} AND resolved_by_team <> 'Service Desk' LIMIT 1)",
    "stale_unresolved_tickets":
        "UPDATE tickets SET status = 'open', resolved_at = NULL, resolution_hours = NULL, "
        "resolved_by_team = NULL, sla_breached = NULL, satisfaction_score = NULL, reopened = false "
        f"WHERE ticket_id = ({RESOLVED} AND created_at < '2025-01-01' LIMIT 1)",
    "days_without_tickets":
        "DELETE FROM tickets WHERE created_at::date = '2024-03-12'",
    "unused_reference_rows":
        "INSERT INTO teams VALUES ('Facilities', 2)",
}


def test_every_check_except_duplicates_has_a_planted_problem():
    assert set(PLANTED_PROBLEMS) == set(CHECKS) - {"possible_duplicate_submissions"}


@pytest.mark.db
@pytest.mark.parametrize("name", sorted(PLANTED_PROBLEMS))
def test_check_detects_its_planted_problem(db_conn, name):
    check = CHECKS[name]
    assert run_check(db_conn, check).passed, "check should be quiet before the problem is planted"
    with db_conn.transaction(force_rollback=True):
        db_conn.execute(PLANTED_PROBLEMS[name])
        assert not run_check(db_conn, check).passed


@pytest.mark.db
def test_duplicate_check_finds_a_planted_resubmission(db_conn):
    check = CHECKS["possible_duplicate_submissions"]
    before = run_check(db_conn, check).row_count
    with db_conn.transaction(force_rollback=True):
        db_conn.execute(
            "INSERT INTO tickets "
            "SELECT 'TKT-DUPLICATE', created_at + INTERVAL '2 minutes', channel, requester_type, department, "
            "category, subcategory, ticket_type, priority, assigned_team, description, sla_hours, "
            "sla_due_at + INTERVAL '2 minutes', 'cancelled', NULL, NULL, NULL, 0, false, NULL, NULL "
            "FROM tickets WHERE ticket_id = 'TKT-000001'"
        )
        assert run_check(db_conn, check).row_count == before + 1
