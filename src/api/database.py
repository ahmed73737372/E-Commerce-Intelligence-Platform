"""
src/api/database.py
====================

SQLite connection dependency for FastAPI.

WHY A DEPENDENCY?
-----------------
FastAPI's Depends() system allows the database connection to be:
  - Injected into any route that needs it
  - Overridden in tests with an in-memory SQLite database
  - Automatically closed after each request (via the finally block)

This means the test suite never touches the real database file —
it passes a seeded in-memory connection instead.

USAGE
-----
In a router:
    @router.get("/example")
    def my_route(db: sqlite3.Connection = Depends(get_db)):
        ...

In tests:
    app.dependency_overrides[get_db] = lambda: test_db_connection
"""

import sqlite3
from typing import Generator

import config.settings as cfg


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    FastAPI dependency that opens a SQLite connection for one request,
    then closes it when the request completes.

    - Uses Row factory so results are accessible by column name (row["iso3"])
    - Enables foreign key enforcement
    - Read-only safe: all queries in services.py are SELECT only

    Yields
    ------
    sqlite3.Connection
        A live, configured connection to data/economic_stress.db
    """
    conn = sqlite3.connect(str(cfg.DATABASE_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()
