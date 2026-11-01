-- Similarity search over ticket descriptions.
--
-- `<=>` is pgvector's cosine distance. The nearest descriptions are found
-- first, then each is matched to its latest ticket from before %(before)s, so
-- a result can never come from after the ticket being looked at. One ticket per
-- description keeps results varied, because many tickets share the same text.
-- The pool is larger than the limit because some descriptions only have tickets
-- from later on.


-- name: nearest
WITH nearest AS (
    SELECT description, embedding <=> %(vector)s::vector AS distance
    FROM description_embeddings
    ORDER BY distance
    LIMIT %(pool)s
)
SELECT
    t.ticket_id,
    t.description,
    t.subcategory,
    t.assigned_team,
    t.priority,
    t.created_at,
    t.status,
    t.resolution_hours,
    t.sla_breached,
    round((1 - n.distance)::numeric, 3)::float AS similarity
FROM nearest AS n
CROSS JOIN LATERAL (
    SELECT *
    FROM tickets AS t
    WHERE t.description = n.description
      AND t.created_at < %(before)s
    ORDER BY t.created_at DESC
    LIMIT 1
) AS t
ORDER BY n.distance, t.created_at DESC
LIMIT %(limit)s;


-- name: ticket_embedding
SELECT e.embedding::text AS vector, t.created_at
FROM tickets AS t
LEFT JOIN description_embeddings AS e USING (description)
WHERE t.ticket_id = %(ticket_id)s;
