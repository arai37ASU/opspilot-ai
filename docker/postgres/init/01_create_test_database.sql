-- Separate database for integration tests, so running pytest never
-- overwrites the data used for analysis.
CREATE DATABASE opspilot_test;
