-- Which teams carry the most load, and does a busier queue mean more breaches?


-- name: tickets_per_agent
-- Demand at first routing (assigned_team), per agent per working day.
-- All tickets are divided by working days, so weekend tickets are spread
-- over the week; this is a comparison between teams, not a shift plan.
WITH working_days AS (
    SELECT count(*) AS days
    FROM calendar_days
    WHERE NOT is_weekend AND NOT is_holiday
)
SELECT
    t.assigned_team                                        AS team,
    tm.agents,
    count(*)                                               AS tickets,
    round(count(*)::numeric / tm.agents / w.days, 2)       AS tickets_per_agent_per_working_day
FROM tickets AS t
JOIN teams AS tm ON tm.team = t.assigned_team
CROSS JOIN working_days AS w
GROUP BY t.assigned_team, tm.agents, w.days
ORDER BY tickets_per_agent_per_working_day DESC;


-- name: breach_by_backlog
-- Backlog at arrival: tickets already routed to the same team and not yet
-- resolved when this ticket came in. It is computed as a running total over
-- an event stream (+1 when a ticket arrives, -1 when it is resolved), which
-- takes one pass instead of comparing every ticket with every earlier one.
--
-- Uses assigned_team because that is what is known when the ticket arrives.
-- Cancelled tickets are left out: their cancellation time is not recorded.
-- The P3 column holds priority fixed, so the trend is not just a priority mix effect.
WITH events AS (
    SELECT assigned_team AS team, created_at AS at, 1 AS change, ticket_id
    FROM tickets
    WHERE status <> 'cancelled'
    UNION ALL
    SELECT assigned_team, resolved_at, -1, NULL
    FROM tickets
    WHERE resolved_at IS NOT NULL
),
running AS (
    -- At equal timestamps resolutions (-1) sort first, so a ticket resolved in
    -- the same second no longer counts as open. Ties between arrivals follow
    -- ticket_id, which is creation order.
    SELECT
        ticket_id,
        team,
        change,
        sum(change) OVER (PARTITION BY team ORDER BY at, change, ticket_id ROWS UNBOUNDED PRECEDING) - change
            AS open_at_arrival
    FROM events
),
labelled AS (
    SELECT
        t.priority,
        t.sla_breached,
        CASE
            WHEN r.open_at_arrival::numeric / tm.agents < 1 THEN '0-1'
            WHEN r.open_at_arrival::numeric / tm.agents < 2 THEN '1-2'
            WHEN r.open_at_arrival::numeric / tm.agents < 4 THEN '2-4'
            WHEN r.open_at_arrival::numeric / tm.agents < 6 THEN '4-6'
            ELSE '6+'
        END AS open_tickets_per_agent
    FROM running AS r
    JOIN tickets AS t USING (ticket_id)
    JOIN teams AS tm ON tm.team = r.team
    WHERE r.change = 1
      AND t.status = 'resolved'
)
SELECT
    open_tickets_per_agent,
    count(*)                                                          AS resolved,
    round(100 * avg(sla_breached::int), 1)                            AS breach_rate_pct,
    round(100 * avg(sla_breached::int) FILTER (WHERE priority = 'P3'), 1) AS p3_breach_rate_pct
FROM labelled
GROUP BY open_tickets_per_agent
ORDER BY open_tickets_per_agent;
