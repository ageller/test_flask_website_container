-- Run at every startup by the app factory. IF NOT EXISTS makes it idempotent.
CREATE TABLE IF NOT EXISTS submissions (
    id                   INTEGER PRIMARY KEY,
    created_at           TEXT    NOT NULL,  -- UTC, ISO 8601
    name                 TEXT,              -- NULL means anonymous
    language             TEXT    NOT NULL,
    container_experience INTEGER NOT NULL CHECK (container_experience BETWEEN 1 AND 5),
    environments         TEXT    NOT NULL,  -- JSON array, for example ["Laptop", "AWS"]
    comments             TEXT
);
