-- One row per ticket with features that were known at the moment the ticket
-- was created, plus the training label (sla_breached).
--
-- Leakage rules (docs/dataset_design.md section 8):
--   * No post-creation columns: resolved_at, resolution_hours,
--     resolved_by_team, reassignment_count, reopened, satisfaction_score.
--   * Counts over earlier tickets use only tickets created strictly before
--     this one (EXCLUDE GROUP removes the ticket and anything at the same
--     second).
--   * Historical outcomes use only tickets *resolved* before this ticket was
--     created. A ticket created earlier but resolved later had no known
--     outcome yet.
--   * Team features use assigned_team, the team known at creation.
--
-- Known approximation: cancelled tickets are left out of the open backlog
-- because their cancellation time is not recorded. Cancellations are mostly
-- quick duplicates, so the effect is small, but it does use the final status.
--
-- Historical rates are NULL until a team or subcategory has resolved
-- tickets in the window, so the first weeks of data have missing values.
--
-- Materialized so the window passes run once per load, not on every read.

DROP MATERIALIZED VIEW IF EXISTS ticket_features;

CREATE MATERIALIZED VIEW ticket_features AS
WITH backlog AS (
    -- Running total over arrival (+1) and resolution (-1) events; see
    -- sql/analysis/02_team_workload.sql for the reasoning behind the ordering.
    SELECT ticket_id, open_at_arrival
    FROM (
        SELECT
            ticket_id,
            change,
            sum(change) OVER (PARTITION BY team ORDER BY at, change, ticket_id ROWS UNBOUNDED PRECEDING) - change
                AS open_at_arrival
        FROM (
            SELECT assigned_team AS team, created_at AS at, 1 AS change, ticket_id
            FROM tickets
            WHERE status <> 'cancelled'
            UNION ALL
            SELECT assigned_team, resolved_at, -1, NULL
            FROM tickets
            WHERE resolved_at IS NOT NULL
        ) AS events
    ) AS running
    WHERE change = 1
),
recent_arrivals AS (
    SELECT
        ticket_id,
        count(*) OVER (
            PARTITION BY assigned_team ORDER BY created_at
            RANGE BETWEEN INTERVAL '24 hours' PRECEDING AND CURRENT ROW EXCLUDE GROUP
        ) AS team_arrivals_prev_24h,
        count(*) OVER (
            PARTITION BY subcategory ORDER BY created_at
            RANGE BETWEEN INTERVAL '2 hours' PRECEDING AND CURRENT ROW EXCLUDE GROUP
        ) AS subcategory_arrivals_prev_2h,
        count(*) OVER (
            PARTITION BY subcategory ORDER BY created_at
            RANGE BETWEEN INTERVAL '24 hours' PRECEDING AND CURRENT ROW EXCLUDE GROUP
        ) AS subcategory_arrivals_prev_24h
    FROM tickets
),
team_history AS (
    -- Arrival rows carry zeros and resolution rows carry outcomes, so the
    -- window sums at an arrival count only resolutions before it.
    SELECT ticket_id, resolved_prev_30d, breached_prev_30d
    FROM (
        SELECT
            ticket_id,
            sum(resolved) OVER w AS resolved_prev_30d,
            sum(breached) OVER w AS breached_prev_30d
        FROM (
            SELECT assigned_team AS team, created_at AS at, ticket_id, 0 AS resolved, 0 AS breached
            FROM tickets
            UNION ALL
            SELECT assigned_team, resolved_at, NULL, 1, sla_breached::int
            FROM tickets
            WHERE sla_breached IS NOT NULL
        ) AS events
        WINDOW w AS (
            PARTITION BY team ORDER BY at
            RANGE BETWEEN INTERVAL '30 days' PRECEDING AND CURRENT ROW EXCLUDE GROUP
        )
    ) AS windowed
    WHERE ticket_id IS NOT NULL
),
subcategory_history AS (
    -- Same pattern over 90 days, since most subcategories are smaller than teams.
    SELECT ticket_id, resolved_prev_90d, breached_prev_90d
    FROM (
        SELECT
            ticket_id,
            sum(resolved) OVER w AS resolved_prev_90d,
            sum(breached) OVER w AS breached_prev_90d
        FROM (
            SELECT subcategory, created_at AS at, ticket_id, 0 AS resolved, 0 AS breached
            FROM tickets
            UNION ALL
            SELECT subcategory, resolved_at, NULL, 1, sla_breached::int
            FROM tickets
            WHERE sla_breached IS NOT NULL
        ) AS events
        WINDOW w AS (
            PARTITION BY subcategory ORDER BY at
            RANGE BETWEEN INTERVAL '90 days' PRECEDING AND CURRENT ROW EXCLUDE GROUP
        )
    ) AS windowed
    WHERE ticket_id IS NOT NULL
)
SELECT
    t.ticket_id,
    t.created_at,
    t.sla_breached,  -- label, NULL when the ticket has no outcome yet

    -- Submitted fields
    t.channel,
    t.requester_type,
    t.department,
    t.category,
    t.subcategory,
    t.ticket_type,
    t.priority,
    t.assigned_team,
    t.sla_hours,
    t.description,

    -- Time of arrival
    extract(hour FROM t.created_at)::int AS hour_of_day,
    c.day_of_week,
    c.is_weekend,
    c.is_holiday,
    c.academic_period,
    round((extract(epoch FROM greatest(staffed.opens, t.created_at) - t.created_at) / 3600)::numeric, 2)
        AS hours_until_staffed,

    -- Workload of the assigned team
    tm.agents AS team_agents,
    b.open_at_arrival AS team_open_at_arrival,
    round(b.open_at_arrival::numeric / tm.agents, 2) AS team_open_per_agent,
    ra.team_arrivals_prev_24h,

    -- Similar recent tickets
    ra.subcategory_arrivals_prev_2h,
    ra.subcategory_arrivals_prev_24h,

    -- Recent outcomes, from tickets resolved before this one was created
    coalesce(th.resolved_prev_30d, 0) AS team_resolved_prev_30d,
    round(th.breached_prev_30d::numeric / nullif(th.resolved_prev_30d, 0), 4) AS team_breach_rate_prev_30d,
    coalesce(sh.resolved_prev_90d, 0) AS subcategory_resolved_prev_90d,
    round(sh.breached_prev_90d::numeric / nullif(sh.resolved_prev_90d, 0), 4) AS subcategory_breach_rate_prev_90d,

    -- Description
    length(t.description) AS description_length,
    t.description ~* '(urgent|asap|as soon as possible|blocking)' AS mentions_urgency
FROM tickets AS t
JOIN calendar_days AS c ON c.day = t.created_at::date
JOIN teams AS tm ON tm.team = t.assigned_team
JOIN recent_arrivals AS ra USING (ticket_id)
LEFT JOIN backlog AS b USING (ticket_id)
LEFT JOIN team_history AS th USING (ticket_id)
LEFT JOIN subcategory_history AS sh USING (ticket_id)
-- Opening time of the first staffed period that has not already closed when
-- the ticket arrives (weekdays 08:00-18:00, weekends and holidays 10:00-16:00).
-- These are the desk's published hours, so they are known at creation.
-- NULL for tickets after the last staffed period in the calendar.
LEFT JOIN LATERAL (
    SELECT opens
    FROM (
        SELECT
            d.day + CASE WHEN d.is_weekend OR d.is_holiday THEN TIME '10:00' ELSE TIME '08:00' END AS opens,
            d.day + CASE WHEN d.is_weekend OR d.is_holiday THEN TIME '16:00' ELSE TIME '18:00' END AS closes
        FROM calendar_days AS d
        WHERE d.day BETWEEN t.created_at::date AND t.created_at::date + 3
    ) AS periods
    WHERE closes > t.created_at
    ORDER BY opens
    LIMIT 1
) AS staffed ON true;

-- A unique index allows REFRESH MATERIALIZED VIEW CONCURRENTLY later, which
-- refreshes without blocking readers.
CREATE UNIQUE INDEX ticket_features_ticket_id_idx ON ticket_features (ticket_id);
