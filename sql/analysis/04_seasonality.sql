-- How do volume and SLA performance change across the academic calendar?


-- name: by_academic_period
-- Starts from calendar_days so the day count includes every day in a period,
-- not only days that had tickets.
SELECT
    c.academic_period,
    count(DISTINCT c.day)                                         AS days,
    count(t.ticket_id)                                            AS tickets,
    round(count(t.ticket_id)::numeric / count(DISTINCT c.day), 1) AS tickets_per_day,
    round(100 * avg(t.sla_breached::int), 1)                      AS breach_rate_pct
FROM calendar_days AS c
LEFT JOIN tickets AS t ON t.created_at::date = c.day
GROUP BY c.academic_period
ORDER BY tickets_per_day DESC;


-- name: team_breach_by_period
-- One column per period (a pivot using FILTER), sorted by how much worse each
-- team does at semester start than in regular weeks.
SELECT *, semester_start_pct - regular_pct AS semester_start_increase_pts
FROM (
    SELECT
        t.resolved_by_team AS team,
        round(100 * avg(t.sla_breached::int) FILTER (WHERE c.academic_period = 'regular'), 1)        AS regular_pct,
        round(100 * avg(t.sla_breached::int) FILTER (WHERE c.academic_period = 'semester_start'), 1) AS semester_start_pct,
        round(100 * avg(t.sla_breached::int) FILTER (WHERE c.academic_period = 'summer'), 1)         AS summer_pct,
        round(100 * avg(t.sla_breached::int) FILTER (WHERE c.academic_period = 'winter_break'), 1)   AS winter_break_pct
    FROM tickets AS t
    JOIN calendar_days AS c ON c.day = t.created_at::date
    WHERE t.status = 'resolved'
    GROUP BY t.resolved_by_team
) AS by_team
ORDER BY semester_start_increase_pts DESC;
