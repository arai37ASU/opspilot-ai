-- KPI queries served by the API's /metrics endpoints.
--
-- Each query takes a date range, %(start)s to %(end)s inclusive, on the
-- ticket's creation date. Breach rates are over resolved tickets only, as in
-- sql/analysis; a test checks that the full-range results agree with the
-- saved analysis results in reports/sql.


-- name: overview
SELECT
    count(*)                                                       AS tickets,
    count(*) FILTER (WHERE status = 'resolved')                    AS resolved,
    count(*) FILTER (WHERE status IN ('open', 'in_progress'))      AS unresolved,
    count(*) FILTER (WHERE sla_breached)                           AS breached,
    round(100 * avg(sla_breached::int), 1)                         AS breach_rate_pct,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_resolution_hours,
    round(avg(satisfaction_score), 2)                              AS mean_satisfaction,
    round(100.0 * count(satisfaction_score) / nullif(count(*) FILTER (WHERE status = 'resolved'), 0), 1)
                                                                   AS survey_response_rate_pct
FROM tickets
WHERE created_at::date BETWEEN %(start)s AND %(end)s;


-- name: by_priority
SELECT
    priority,
    count(*) FILTER (WHERE status = 'resolved')  AS resolved,
    round(100 * avg(sla_breached::int), 1)       AS breach_rate_pct
FROM tickets
WHERE created_at::date BETWEEN %(start)s AND %(end)s
GROUP BY priority
ORDER BY priority;


-- name: by_team
-- Volume and misrouting by the team a ticket was first assigned to; breach
-- rate and resolution time by the team that resolved it, as in sql/analysis.
WITH assigned AS (
    SELECT
        t.assigned_team AS team,
        count(*) AS tickets,
        round(100 * avg((t.assigned_team <> s.owning_team)::int), 1) AS misrouted_pct
    FROM tickets AS t
    JOIN subcategories AS s USING (subcategory)
    WHERE t.created_at::date BETWEEN %(start)s AND %(end)s
    GROUP BY t.assigned_team
),
resolved AS (
    SELECT
        resolved_by_team AS team,
        count(*) AS resolved,
        round(100 * avg(sla_breached::int), 1) AS breach_rate_pct,
        round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_resolution_hours
    FROM tickets
    WHERE status = 'resolved' AND created_at::date BETWEEN %(start)s AND %(end)s
    GROUP BY resolved_by_team
)
SELECT
    tm.team,
    tm.agents,
    coalesce(a.tickets, 0) AS tickets,
    coalesce(r.resolved, 0) AS resolved,
    r.breach_rate_pct,
    r.median_resolution_hours,
    a.misrouted_pct
FROM teams AS tm
LEFT JOIN assigned AS a USING (team)
LEFT JOIN resolved AS r USING (team)
ORDER BY r.breach_rate_pct DESC NULLS LAST;


-- name: monthly_trend
SELECT
    date_trunc('month', created_at)::date AS month,
    count(*)                              AS tickets,
    round(100 * avg(sla_breached::int), 1) AS breach_rate_pct
FROM tickets
GROUP BY 1
ORDER BY 1;
