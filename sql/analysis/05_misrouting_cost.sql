-- What does sending a ticket to the wrong team first cost?
--
-- A ticket is misrouted when its first assigned team is not the team that
-- owns its subcategory in the service catalogue. Medians are used for time
-- because resolution times are heavily right-skewed.


-- name: misrouted_vs_correct
SELECT
    t.assigned_team <> s.owning_team                                                  AS misrouted,
    count(*)                                                                          AS resolved,
    round(percentile_cont(0.5) WITHIN GROUP (ORDER BY t.resolution_hours)::numeric, 1) AS median_hours,
    round(avg(t.reassignment_count), 2)                                               AS avg_reassignments,
    round(100 * avg(t.sla_breached::int), 1)                                          AS breach_rate_pct
FROM tickets AS t
JOIN subcategories AS s USING (subcategory)
WHERE t.status = 'resolved'
GROUP BY 1
ORDER BY 1;


-- name: by_owning_team
SELECT
    s.owning_team                                                              AS team,
    count(*)                                                                   AS resolved,
    round(100 * avg((t.assigned_team <> s.owning_team)::int), 1)               AS misrouted_pct,
    round(100 * avg(t.sla_breached::int) FILTER (WHERE t.assigned_team <> s.owning_team), 1) AS misrouted_breach_pct,
    round(100 * avg(t.sla_breached::int) FILTER (WHERE t.assigned_team = s.owning_team), 1)  AS correct_breach_pct,
    round((
        percentile_cont(0.5) WITHIN GROUP (ORDER BY t.resolution_hours) FILTER (WHERE t.assigned_team <> s.owning_team)
        - percentile_cont(0.5) WITHIN GROUP (ORDER BY t.resolution_hours) FILTER (WHERE t.assigned_team = s.owning_team)
    )::numeric, 1)                                                             AS extra_median_hours
FROM tickets AS t
JOIN subcategories AS s USING (subcategory)
WHERE t.status = 'resolved'
GROUP BY s.owning_team
ORDER BY extra_median_hours DESC;
