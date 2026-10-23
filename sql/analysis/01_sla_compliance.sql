-- How often do resolved tickets meet their SLA target, and where do they not?
--
-- Breach rates are over resolved tickets only: avg() skips NULLs, and
-- sla_breached is NULL for tickets that have no outcome yet.


-- name: overall
SELECT
    count(*)                                     AS tickets,
    count(*) FILTER (WHERE status = 'resolved')  AS resolved,
    count(*) FILTER (WHERE sla_breached)         AS breached,
    round(100 * avg(sla_breached::int), 1)       AS breach_rate_pct
FROM tickets;


-- name: by_priority
SELECT
    priority,
    count(*) FILTER (WHERE status = 'resolved')  AS resolved,
    round(100 * avg(sla_breached::int), 1)       AS breach_rate_pct
FROM tickets
GROUP BY priority
ORDER BY priority;


-- name: by_team
-- Grouped by the team that resolved the ticket, with its headcount.
SELECT
    t.resolved_by_team                      AS team,
    tm.agents,
    count(*)                                AS resolved,
    round(100 * avg(t.sla_breached::int), 1) AS breach_rate_pct
FROM tickets AS t
JOIN teams AS tm ON tm.team = t.resolved_by_team
WHERE t.status = 'resolved'
GROUP BY t.resolved_by_team, tm.agents
ORDER BY breach_rate_pct DESC;


-- name: by_category
SELECT
    category,
    count(*)                                AS resolved,
    round(100 * avg(sla_breached::int), 1)  AS breach_rate_pct
FROM tickets
WHERE status = 'resolved'
GROUP BY category
ORDER BY breach_rate_pct DESC;


-- name: monthly_trend
-- The rolling column is a plain average of the last three monthly rates,
-- which smooths month-to-month noise when reading the trend.
WITH monthly AS (
    SELECT
        date_trunc('month', created_at)::date AS month,
        count(*)                              AS tickets,
        avg(sla_breached::int)                AS breach_rate
    FROM tickets
    GROUP BY 1
)
SELECT
    month,
    tickets,
    round(100 * breach_rate, 1) AS breach_rate_pct,
    round(100 * avg(breach_rate) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 1)
        AS rolling_3_month_pct
FROM monthly
ORDER BY month;
