"""SQLite helpers.

Why SQLite is acceptable for this demo: everything runs on a single host, the
write volume is tiny, and the whole database is one file in a named Docker
volume. WAL mode plus a busy timeout lets the two gunicorn workers share it.

What would change for a real project: store data in a managed database (for
example PostgreSQL run by a cloud provider or central IT) or send it to an API
such as REDCap. Either one gives you backups, access control, and audit trails
that a file in a volume does not.
"""

import os
import sqlite3

from flask import current_app, g


def connect(path):
    """Open a connection with the settings every connection must have."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        # busy_timeout comes first so the WAL switch can wait for a lock held
        # by the other gunicorn worker instead of failing immediately.
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def get_db():
    """Return this request's connection, opening it on first use."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(exc=None):
    """Close this request's connection at teardown. Never shared across requests."""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(app):
    """Create the database file and table if needed. Safe to run on every start."""
    path = app.config["DATABASE_PATH"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = connect(path)
    try:
        with app.open_resource("schema.sql") as f:
            conn.executescript(f.read().decode("utf-8"))
        conn.commit()
    finally:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)
    init_db(app)
