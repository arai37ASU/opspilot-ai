-- Indexes are created after the bulk load: building an index once over
-- loaded data is faster than updating it for every inserted row.

-- Time-range filters and monthly trends.
CREATE INDEX tickets_created_at_idx ON tickets (created_at);

-- Per-team questions over time, such as backlog at the moment a ticket
-- arrives, which compares each ticket with earlier tickets of the same team.
-- assigned_team rather than resolved_by_team because it is known at creation.
CREATE INDEX tickets_team_created_at_idx ON tickets (assigned_team, created_at);

-- Bursts of the same issue (recurring-issue and incident detection).
CREATE INDEX tickets_subcategory_created_at_idx ON tickets (subcategory, created_at);
