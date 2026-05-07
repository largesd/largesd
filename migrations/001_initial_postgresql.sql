-- Initial PostgreSQL migration for debate_system
-- Run: psql $DATABASE_URL -f migrations/001_initial_postgresql.sql

-- Convert SQLite datetime TEXT to PostgreSQL TIMESTAMP where needed
-- Note: SQLite schema is already mostly PostgreSQL-compatible.
-- Key differences to address:
--   1. SQLite AUTOINCREMENT -> PostgreSQL SERIAL
--   2. SQLite TEXT -> PostgreSQL TEXT/VARCHAR/TIMESTAMP as appropriate
--   3. SQLite INTEGER boolean -> PostgreSQL BOOLEAN

-- Example table conversion (repeat for all tables):
-- CREATE TABLE debates (
--     debate_id VARCHAR PRIMARY KEY,
--     resolution TEXT NOT NULL,
--     scope TEXT,
--     moderation_criteria TEXT,
--     debate_frame TEXT,
--     created_at TIMESTAMP NOT NULL,
--     current_snapshot_id VARCHAR,
--     user_id VARCHAR,
--     active_frame_id VARCHAR,
--     is_private BOOLEAN DEFAULT FALSE
-- );

-- For a full migration, use a tool like pgloader or write a Python script
-- that copies data from SQLite to PostgreSQL while transforming types.
