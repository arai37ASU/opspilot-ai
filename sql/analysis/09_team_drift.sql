-- Has any team's performance changed over time?
--
-- Year-over-year comparison by quarter removes the academic calendar from the
-- comparison: Q2 2025 is compared with Q2 2024, not with Q1 2025.


-- name: quarterly_by_team
-- lag(..., 4) is the same quarter one year earlier. That holds because every
-- team has tickets in every quarter.
WITH quarterly AS (
    SELECT
        resolved_by_team                         AS team,
        date_trunc('quarter', created_at)::date  AS quarter,
        count(*)                                 AS resolved,
        avg(sla_breached::int)                   AS breach_rate
    FROM tickets
    WHERE status = 'resolved'
    GROUP BY 1, 2
)
SELECT
    team,
    quarter,
    resolved,
    round(100 * breach_rate, 1)                               AS breach_rate_pct,
    round(100 * (breach_rate - lag(breach_rate, 4) OVER w), 1) AS change_vs_year_before_pts
FROM quarterly
WINDOW w AS (PARTITION BY team ORDER BY quarter)
ORDER BY team, quarter;


-- name: largest_year_over_year_changes
WITH quarterly AS (
    SELECT
        resolved_by_team                         AS team,
        date_trunc('quarter', created_at)::date  AS quarter,
        avg(sla_breached::int)                   AS breach_rate
    FROM tickets
    WHERE status = 'resolved'
    GROUP BY 1, 2
),
changes AS (
    SELECT
        team,
        quarter,
        breach_rate,
        breach_rate - lag(breach_rate, 4) OVER (PARTITION BY team ORDER BY quarter) AS change
    FROM quarterly
)
SELECT
    team,
    quarter,
    round(100 * breach_rate, 1) AS breach_rate_pct,
    round(100 * change, 1)      AS change_vs_year_before_pts
FROM changes
WHERE change IS NOT NULL
ORDER BY abs(change) DESC
LIMIT 5;
