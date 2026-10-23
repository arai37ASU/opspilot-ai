-- Data-quality checks for the loaded tables.
--
-- Each check is a query that returns the rows breaking one rule, so an empty
-- result means the check passed. Rules that can be decided from a single row
-- are enforced as constraints in sql/schema; these cover what constraints
-- cannot: derived columns, cross-table consistency, and patterns that deserve
-- a human look rather than a rejected load.
--
-- Severity:
--   error    must return no rows
--   warning  reported for review; some rows can be legitimate
--
-- Format read by src/opspilot/db/checks.py: every check starts with a
-- "-- name:" line, then "-- severity:", then optional description comments.


-- name: sla_due_at_matches_sla_hours
-- severity: error
-- sla_due_at is derived from created_at and sla_hours and must agree with them.
SELECT ticket_id, created_at, sla_hours, sla_due_at
FROM tickets
WHERE sla_due_at <> created_at + sla_hours * INTERVAL '1 hour';


-- name: resolution_hours_match_timestamps
-- severity: error
-- resolution_hours is rounded to two decimals, so allow half a hundredth of an hour.
SELECT ticket_id, created_at, resolved_at, resolution_hours
FROM tickets
WHERE resolved_at IS NOT NULL
  AND abs(extract(epoch FROM resolved_at - created_at) / 3600 - resolution_hours) > 0.005;


-- name: sla_hours_match_policy
-- severity: error
-- The SLA policy has not changed during the data period, so every ticket
-- should carry the current target. If policies ever change, this becomes a
-- warning and the check should compare against the policy in force at creation.
SELECT t.ticket_id, t.ticket_type, t.priority, t.sla_hours, p.sla_hours AS policy_hours
FROM tickets AS t
JOIN sla_policies AS p USING (ticket_type, priority)
WHERE t.sla_hours <> p.sla_hours;


-- name: created_within_calendar
-- severity: error
-- Every ticket should fall on a day covered by the date dimension.
SELECT t.ticket_id, t.created_at
FROM tickets AS t
LEFT JOIN calendar_days AS c ON c.day = t.created_at::date
WHERE c.day IS NULL;


-- name: resolved_before_snapshot
-- severity: error
-- The data is a snapshot taken at the end of the last calendar day.
SELECT ticket_id, resolved_at
FROM tickets
WHERE resolved_at >= (SELECT max(day) + 1 FROM calendar_days);


-- name: team_change_has_reassignment
-- severity: error
-- A ticket resolved by a different team than it was assigned to must have
-- been reassigned at least once.
SELECT ticket_id, assigned_team, resolved_by_team, reassignment_count
FROM tickets
WHERE resolved_by_team <> assigned_team
  AND reassignment_count = 0;


-- name: blank_description
-- severity: error
-- NOT NULL allows an empty or whitespace-only string.
SELECT ticket_id, description
FROM tickets
WHERE btrim(description) = '';


-- name: unexpected_department
-- severity: error
-- Department has no reference table, so check it against the known list.
-- This is where inconsistent spellings or casing would show up.
SELECT ticket_id, department
FROM tickets
WHERE department NOT IN (
    'Engineering', 'Arts & Sciences', 'Business School', 'Health Sciences', 'Library',
    'Finance', 'Human Resources', 'Admissions', 'Student Services', 'Research Office'
);


-- name: resolved_outside_owning_team
-- severity: warning
-- Normally the team that owns a subcategory resolves it. Exceptions can be
-- legitimate (a specialist steps in) but are worth a look.
SELECT t.ticket_id, t.subcategory, s.owning_team, t.resolved_by_team
FROM tickets AS t
JOIN subcategories AS s USING (subcategory)
WHERE t.resolved_by_team <> s.owning_team;


-- name: stale_unresolved_tickets
-- severity: warning
-- Open tickets older than 30 days at the snapshot are likely forgotten.
SELECT ticket_id, created_at, status
FROM tickets
WHERE status IN ('open', 'in_progress')
  AND created_at < (SELECT max(day) + 1 FROM calendar_days) - INTERVAL '30 days';


-- name: possible_duplicate_submissions
-- severity: warning
-- Same text from the same department and channel within 10 minutes. During a
-- major incident these are often separate people with the same problem, so
-- they are not removed automatically.
SELECT later.ticket_id, earlier.ticket_id AS earlier_ticket_id, later.description
FROM tickets AS later
JOIN tickets AS earlier
  ON earlier.description = later.description
 AND earlier.department = later.department
 AND earlier.channel = later.channel
 AND earlier.created_at < later.created_at
 AND earlier.created_at >= later.created_at - INTERVAL '10 minutes';


-- name: days_without_tickets
-- severity: warning
-- A day with no tickets at all usually means missing data, not a quiet day.
SELECT c.day
FROM calendar_days AS c
LEFT JOIN tickets AS t ON t.created_at::date = c.day
WHERE t.ticket_id IS NULL;


-- name: unused_reference_rows
-- severity: warning
-- Catalogue entries or teams that never appear may be retired or mistyped.
SELECT 'subcategory' AS kind, s.subcategory AS value
FROM subcategories AS s
WHERE NOT EXISTS (SELECT 1 FROM tickets AS t WHERE t.subcategory = s.subcategory)
UNION ALL
SELECT 'team', tm.team
FROM teams AS tm
WHERE NOT EXISTS (SELECT 1 FROM tickets AS t WHERE t.assigned_team = tm.team);
