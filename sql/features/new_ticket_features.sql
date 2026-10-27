-- Database-derived features for one ticket at the moment it is created.
--
-- This is the serving-time version of sql/features/ticket_features.sql. Every
-- expression must give exactly the value the view gives for a stored ticket;
-- tests/test_online_features.py checks that on thousands of tickets. A
-- difference would mean the model sees inputs at prediction time that it
-- never saw in training (training/serving skew).
--
-- Parameters:
--   created_at, assigned_team, subcategory
--   ticket_id: NULL for a new ticket. For a stored ticket, its id, so that
--     tickets created in the same second are ordered the way the view orders
--     them (by ticket_id) and the ticket does not count itself.
--
-- Only rows created or resolved before created_at are used, so the result is
-- the same whether or not later tickets are already in the database.

WITH input AS (
    SELECT
        %(created_at)s::timestamp AS created_at,
        %(assigned_team)s::text AS assigned_team,
        %(subcategory)s::text AS subcategory,
        %(ticket_id)s::text AS ticket_id
)
SELECT
    extract(hour FROM i.created_at)::int AS hour_of_day,
    c.day_of_week,
    c.is_weekend,
    c.is_holiday,
    c.academic_period,
    round((extract(epoch FROM greatest(staffed.opens, i.created_at) - i.created_at) / 3600)::numeric, 2)
        AS hours_until_staffed,
    round(backlog.open_tickets::numeric / tm.agents, 2) AS team_open_per_agent,
    recent.prev_2h AS subcategory_arrivals_prev_2h,
    recent.prev_24h AS subcategory_arrivals_prev_24h,
    team_history.resolved AS team_resolved_prev_30d,
    round(team_history.breached::numeric / nullif(team_history.resolved, 0), 4) AS team_breach_rate_prev_30d,
    subcategory_history.resolved AS subcategory_resolved_prev_90d,
    round(subcategory_history.breached::numeric / nullif(subcategory_history.resolved, 0), 4)
        AS subcategory_breach_rate_prev_90d
FROM input AS i
JOIN calendar_days AS c ON c.day = i.created_at::date
JOIN teams AS tm ON tm.team = i.assigned_team
-- Open backlog: the team's earlier, non-cancelled tickets not resolved by now.
-- A resolution at exactly created_at counts as already resolved, as in the view.
CROSS JOIN LATERAL (
    SELECT count(*) AS open_tickets
    FROM tickets AS o
    WHERE o.assigned_team = i.assigned_team
      AND o.status <> 'cancelled'
      AND (o.created_at < i.created_at
           OR (o.created_at = i.created_at AND i.ticket_id IS NOT NULL AND o.ticket_id < i.ticket_id)
           OR (o.created_at = i.created_at AND i.ticket_id IS NULL))
      AND (o.resolved_at IS NULL OR o.resolved_at > i.created_at)
) AS backlog
-- Same-subcategory tickets created strictly before now (the view's EXCLUDE GROUP).
CROSS JOIN LATERAL (
    SELECT
        count(*) FILTER (WHERE o.created_at >= i.created_at - INTERVAL '2 hours') AS prev_2h,
        count(*) AS prev_24h
    FROM tickets AS o
    WHERE o.subcategory = i.subcategory
      AND o.created_at >= i.created_at - INTERVAL '24 hours'
      AND o.created_at < i.created_at
) AS recent
-- Outcomes known before now: tickets resolved in the window, not at this moment.
CROSS JOIN LATERAL (
    SELECT count(*) AS resolved, sum(o.sla_breached::int) AS breached
    FROM tickets AS o
    WHERE o.assigned_team = i.assigned_team
      AND o.sla_breached IS NOT NULL
      AND o.resolved_at >= i.created_at - INTERVAL '30 days'
      AND o.resolved_at < i.created_at
) AS team_history
CROSS JOIN LATERAL (
    SELECT count(*) AS resolved, sum(o.sla_breached::int) AS breached
    FROM tickets AS o
    WHERE o.subcategory = i.subcategory
      AND o.sla_breached IS NOT NULL
      AND o.resolved_at >= i.created_at - INTERVAL '90 days'
      AND o.resolved_at < i.created_at
) AS subcategory_history
LEFT JOIN LATERAL (
    SELECT opens
    FROM (
        SELECT
            d.day + CASE WHEN d.is_weekend OR d.is_holiday THEN TIME '10:00' ELSE TIME '08:00' END AS opens,
            d.day + CASE WHEN d.is_weekend OR d.is_holiday THEN TIME '16:00' ELSE TIME '18:00' END AS closes
        FROM calendar_days AS d
        WHERE d.day BETWEEN i.created_at::date AND i.created_at::date + 3
    ) AS periods
    WHERE closes > i.created_at
    ORDER BY opens
    LIMIT 1
) AS staffed ON true;
