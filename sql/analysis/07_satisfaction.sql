-- What drives satisfaction, and how far can the survey be trusted?
--
-- Fewer than a third of resolved tickets get a survey response, and people
-- with very good or very bad experiences answer more often. Survey averages
-- describe respondents, not all requesters.


-- name: response_rate_by_breach
SELECT
    sla_breached,
    count(*)                                                 AS resolved,
    count(satisfaction_score)                                AS responses,
    round(100.0 * count(satisfaction_score) / count(*), 1)   AS response_rate_pct,
    round(avg(satisfaction_score), 2)                        AS mean_score
FROM tickets
WHERE status = 'resolved'
GROUP BY sla_breached
ORDER BY sla_breached;


-- name: score_distribution
SELECT
    satisfaction_score,
    count(*)                                            AS responses,
    round(100.0 * count(*) / sum(count(*)) OVER (), 1)  AS share_pct
FROM tickets
WHERE satisfaction_score IS NOT NULL
GROUP BY satisfaction_score
ORDER BY satisfaction_score;


-- name: by_outcome
-- low_score_pct is the share of responses scoring 1 or 2.
SELECT
    sla_breached,
    reopened,
    count(satisfaction_score)                                  AS responses,
    round(avg(satisfaction_score), 2)                          AS mean_score,
    round(100 * avg((satisfaction_score <= 2)::int), 1)        AS low_score_pct
FROM tickets
WHERE status = 'resolved'
GROUP BY sla_breached, reopened
ORDER BY sla_breached, reopened;


-- name: by_category
SELECT
    category,
    count(satisfaction_score)                            AS responses,
    round(avg(satisfaction_score), 2)                    AS mean_score,
    round(100 * avg((satisfaction_score <= 2)::int), 1)  AS low_score_pct
FROM tickets
WHERE status = 'resolved'
GROUP BY category
ORDER BY mean_score;
