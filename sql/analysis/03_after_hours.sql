-- How much of the breach problem comes from tickets that arrive when the desk
-- is not fully staffed?
--
-- Weekday staffed hours are 08:00-18:00. Weekends and holidays have reduced
-- staffing. The classification is repeated in each query so every query
-- runs on its own.


-- name: by_arrival_window
SELECT
    arrival_window,
    count(*)                                                       AS tickets,
    round(100.0 * count(*) / sum(count(*)) OVER (), 1)             AS share_of_tickets_pct,
    round(100 * avg(sla_breached::int), 1)                         AS breach_rate_pct,
    round(100.0 * count(*) FILTER (WHERE sla_breached)
          / sum(count(*) FILTER (WHERE sla_breached)) OVER (), 1)  AS share_of_breaches_pct
FROM (
    SELECT
        t.sla_breached,
        CASE
            WHEN c.is_weekend OR c.is_holiday THEN 'weekend_or_holiday'
            WHEN extract(hour FROM t.created_at) BETWEEN 8 AND 17 THEN 'weekday_staffed'
            ELSE 'weekday_after_hours'
        END AS arrival_window
    FROM tickets AS t
    JOIN calendar_days AS c ON c.day = t.created_at::date
) AS classified
GROUP BY arrival_window
ORDER BY arrival_window;


-- name: by_priority_and_window
-- P1 tickets go to on-call staff, so they should show little after-hours effect.
SELECT
    priority,
    round(100 * avg(sla_breached::int) FILTER (WHERE arrival_window = 'weekday_staffed'), 1)     AS weekday_staffed_pct,
    round(100 * avg(sla_breached::int) FILTER (WHERE arrival_window = 'weekday_after_hours'), 1) AS weekday_after_hours_pct,
    round(100 * avg(sla_breached::int) FILTER (WHERE arrival_window = 'weekend_or_holiday'), 1)  AS weekend_or_holiday_pct
FROM (
    SELECT
        t.priority,
        t.sla_breached,
        CASE
            WHEN c.is_weekend OR c.is_holiday THEN 'weekend_or_holiday'
            WHEN extract(hour FROM t.created_at) BETWEEN 8 AND 17 THEN 'weekday_staffed'
            ELSE 'weekday_after_hours'
        END AS arrival_window
    FROM tickets AS t
    JOIN calendar_days AS c ON c.day = t.created_at::date
) AS classified
GROUP BY priority
ORDER BY priority;
