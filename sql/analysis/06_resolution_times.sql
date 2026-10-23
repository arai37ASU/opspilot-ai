-- Which issues take longest to resolve, and what does reopening cost?
--
-- The mean is shown next to the median to make the skew visible: a few very
-- long tickets pull the mean well above the typical ticket.


-- name: by_subcategory
SELECT
    subcategory,
    ticket_type,
    count(*)                                                                        AS resolved,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_hours,
    round(percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS p90_hours,
    round(avg(resolution_hours), 1)                                                 AS mean_hours,
    round(100 * avg(sla_breached::int), 1)                                          AS breach_rate_pct
FROM tickets
WHERE status = 'resolved'
GROUP BY subcategory, ticket_type
ORDER BY breach_rate_pct DESC;


-- name: reopen_effect
SELECT
    reopened,
    count(*)                                                                        AS resolved,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_hours,
    round(percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS p90_hours,
    round(100 * avg(sla_breached::int), 1)                                          AS breach_rate_pct
FROM tickets
WHERE status = 'resolved'
GROUP BY reopened
ORDER BY reopened;
