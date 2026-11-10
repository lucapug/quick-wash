"""Real relational database for the repository layer.

The system's database is PostgreSQL, declared in `docker-compose.yml` and reached through
`QW_DATABASE_URL` (the CI service and `docker compose up` both set it). A clean checkout with no
network egress has no reachable PostgreSQL, so the adapter falls back to a file-backed SQLite
database. Both are real relational databases and the repository code above them is identical —
the repository is never mocked, which is what makes the R5 race a persistence-layer fact rather
than a pre-check.
"""

import os
import sqlite3

POSTGRES = "postgres"
SQLITE = "sqlite"

DEFAULT_URL = "postgresql://quickwash:quickwash@127.0.0.1:5432/quickwash"


def default_url() -> str:
    return os.environ.get("QW_DATABASE_URL", DEFAULT_URL)


def connect(url: str | None = None, path: str | None = None) -> "Database":
    """Connect to PostgreSQL when it is reachable, otherwise to the file-backed fallback."""
    url = url or default_url()
    if url.startswith("postgres"):
        try:
            import psycopg
        except ImportError:
            pass
        else:
            try:
                return Database(psycopg.connect(url, connect_timeout=3), POSTGRES, url)
            except Exception:
                # No server reachable from this checkout: fall back, never a mock.
                pass

    if path is None:
        raise ValueError("the sqlite backend needs a file path")
    connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    return Database(connection, SQLITE, path)


class Database:
    def __init__(self, connection, backend: str, target: str) -> None:
        self.connection = connection
        self.backend = backend
        self.target = target

    def _placeholders(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.backend == POSTGRES else sql

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        cursor = self.connection.cursor()
        cursor.execute(self._placeholders(sql), params)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, [row[i] for i in range(len(names))])) for row in cursor.fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict | None:
        found = self.rows(sql, params)
        return found[0] if found else None

    def execute(self, sql: str, params: tuple = ()) -> int:
        cursor = self.connection.cursor()
        cursor.execute(self._placeholders(sql), params)
        count = cursor.rowcount
        self.connection.commit()
        return count

    def rollback(self) -> None:
        self.connection.rollback()

    def close(self) -> None:
        self.connection.close()
