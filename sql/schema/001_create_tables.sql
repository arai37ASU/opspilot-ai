-- Tables for the OpsPilot service-desk dataset.
--
-- Rerunnable: every table is dropped and recreated. The loader runs this file
-- and the data load in a single transaction, so a failed load leaves the
-- previous tables untouched.
--
-- Constraints encode the rules from docs/dataset_design.md. Checks that compare
-- derived columns (for example sla_due_at against created_at + sla_hours) live
-- in sql/checks instead, so a rounding difference is reported, not rejected.

-- The feature view (sql/features) depends on these tables, so it goes first.
DROP MATERIALIZED VIEW IF EXISTS ticket_features;
DROP TABLE IF EXISTS tickets;
DROP TABLE IF EXISTS subcategories;
DROP TABLE IF EXISTS sla_policies;
DROP TABLE IF EXISTS teams;
DROP TABLE IF EXISTS calendar_days;

CREATE TABLE teams (
    team    TEXT PRIMARY KEY,
    agents  SMALLINT NOT NULL CHECK (agents > 0)
);

CREATE TABLE sla_policies (
    ticket_type  TEXT NOT NULL CHECK (ticket_type IN ('incident', 'service_request')),
    priority     TEXT NOT NULL CHECK (priority IN ('P1', 'P2', 'P3', 'P4')),
    sla_hours    NUMERIC(6, 1) NOT NULL CHECK (sla_hours > 0),
    PRIMARY KEY (ticket_type, priority)
);

-- The service catalogue: which category, ticket type and team each
-- subcategory belongs to.
CREATE TABLE subcategories (
    subcategory   TEXT PRIMARY KEY,
    category      TEXT NOT NULL,
    ticket_type   TEXT NOT NULL CHECK (ticket_type IN ('incident', 'service_request')),
    owning_team   TEXT NOT NULL REFERENCES teams (team),
    -- Target for the composite foreign key on tickets.
    UNIQUE (subcategory, category, ticket_type)
);

-- Date dimension, so analysis can join on academic periods and holidays
-- instead of hard-coding dates into queries.
CREATE TABLE calendar_days (
    day              DATE PRIMARY KEY,
    day_of_week      SMALLINT NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),  -- ISO, 1 = Monday
    is_weekend       BOOLEAN NOT NULL,
    is_holiday       BOOLEAN NOT NULL,
    academic_period  TEXT NOT NULL
        CHECK (academic_period IN ('regular', 'semester_start', 'summer', 'winter_break'))
);

CREATE TABLE tickets (
    ticket_id           TEXT PRIMARY KEY,
    -- Campus local time without a time zone. The generator produces naive
    -- local times, and TIMESTAMPTZ in a daylight-saving zone could turn some
    -- of them into times that do not exist.
    created_at          TIMESTAMP NOT NULL,
    channel             TEXT NOT NULL CHECK (channel IN ('portal', 'email', 'phone', 'chat', 'walk_in')),
    requester_type      TEXT NOT NULL CHECK (requester_type IN ('student', 'faculty', 'staff')),
    department          TEXT NOT NULL,
    category            TEXT NOT NULL,
    subcategory         TEXT NOT NULL,
    ticket_type         TEXT NOT NULL,
    priority            TEXT NOT NULL,
    assigned_team       TEXT NOT NULL REFERENCES teams (team),
    description         TEXT NOT NULL,
    -- Copied from sla_policies at creation time on purpose: if the policy
    -- changes later, each ticket keeps the target it was created under.
    sla_hours           NUMERIC(6, 1) NOT NULL CHECK (sla_hours > 0),
    sla_due_at          TIMESTAMP NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('resolved', 'open', 'in_progress', 'cancelled')),
    resolved_at         TIMESTAMP,
    resolution_hours    NUMERIC(8, 2) CHECK (resolution_hours > 0),
    resolved_by_team    TEXT REFERENCES teams (team),
    reassignment_count  SMALLINT NOT NULL CHECK (reassignment_count BETWEEN 0 AND 3),
    reopened            BOOLEAN NOT NULL,
    satisfaction_score  SMALLINT CHECK (satisfaction_score BETWEEN 1 AND 5),
    sla_breached        BOOLEAN,

    -- Category and type must agree with the service catalogue.
    FOREIGN KEY (subcategory, category, ticket_type)
        REFERENCES subcategories (subcategory, category, ticket_type),
    -- Also rules out P1 service requests, which have no policy row.
    FOREIGN KEY (ticket_type, priority) REFERENCES sla_policies (ticket_type, priority),

    CONSTRAINT outcomes_only_when_resolved CHECK (
        (status = 'resolved') = (
            resolved_at IS NOT NULL
            AND resolution_hours IS NOT NULL
            AND resolved_by_team IS NOT NULL
            AND sla_breached IS NOT NULL
        )
    ),
    CONSTRAINT resolved_after_created CHECK (resolved_at > created_at),
    CONSTRAINT breach_matches_definition CHECK (sla_breached = (resolution_hours > sla_hours)),
    CONSTRAINT survey_only_after_resolution CHECK (satisfaction_score IS NULL OR status = 'resolved'),
    CONSTRAINT reopen_only_after_resolution CHECK (status = 'resolved' OR NOT reopened)
);
