-- Which days had an unusual burst of the same issue?
--
-- This uses only ticket data, never the generator's record of which tickets
-- belong to a major incident, so finding the planted incidents here is a real
-- test of the method.
--
-- Daily spikes include both sudden incidents and slower seasonal surges
-- (password resets at semester start). The academic period and the busiest
-- two-hour window help tell them apart: incidents are usually concentrated
-- in a few hours, surges are spread across the day.


-- name: daily_spikes
-- A subcategory-day is a spike when it has at least four times the
-- subcategory's median daily count and at least 15 tickets more than that
-- median. The median keeps the spikes themselves from inflating the baseline,
-- and the absolute margin stops rare issues being flagged for a few tickets.
WITH daily AS (
    -- Every day x subcategory pair, including zero-ticket days, so the
    -- median reflects quiet days too.
    SELECT c.day, s.subcategory, count(t.ticket_id) AS tickets
    FROM calendar_days AS c
    CROSS JOIN subcategories AS s
    LEFT JOIN tickets AS t
        ON t.subcategory = s.subcategory
       AND t.created_at::date = c.day
    GROUP BY c.day, s.subcategory
),
baseline AS (
    SELECT subcategory, percentile_cont(0.5) WITHIN GROUP (ORDER BY tickets) AS typical_daily
    FROM daily
    GROUP BY subcategory
),
spikes AS (
    SELECT d.day, d.subcategory, d.tickets, b.typical_daily
    FROM daily AS d
    JOIN baseline AS b USING (subcategory)
    WHERE d.tickets >= 4 * b.typical_daily
      AND d.tickets - b.typical_daily >= 15
),
two_hour_counts AS (
    -- For each ticket on a spike day, how many same-subcategory tickets
    -- arrived in the two hours up to and including it.
    SELECT
        t.subcategory,
        t.created_at::date AS day,
        count(*) OVER (
            PARTITION BY t.subcategory
            ORDER BY t.created_at
            RANGE BETWEEN INTERVAL '2 hours' PRECEDING AND CURRENT ROW
        ) AS in_window
    FROM tickets AS t
    JOIN spikes AS s
        ON s.subcategory = t.subcategory
       AND s.day = t.created_at::date
)
SELECT
    s.day,
    c.academic_period,
    s.subcategory,
    s.tickets,
    s.typical_daily,
    max(w.in_window) AS peak_two_hours
FROM spikes AS s
JOIN calendar_days AS c USING (day)
JOIN two_hour_counts AS w USING (subcategory, day)
GROUP BY s.day, c.academic_period, s.subcategory, s.tickets, s.typical_daily
ORDER BY s.day, s.subcategory;
