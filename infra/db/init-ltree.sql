-- Enable extensions required by HR service migrations.
-- Runs automatically on first database creation.
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
