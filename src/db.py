"""Real relational database for the repository layer.

The system's database is PostgreSQL, declared in `docker-compose.yml` and reached through
`QW_DATABASE_URL` (the CI service and `docker compose up` both set it). A clean checkout with no
network egress has no reachable PostgreSQL, so the adapter falls back to a file-backed SQLite
database. Both are real relational databases and the repository code above them is identical — the
repository is never mocked, which is what makes the R5 race a persistence-layer fact rather
than a pre-check.

Two things make that race observable rather than asserted (issue #11, slice b1), and they are the whole
of what this module owns:

1. **One connection per thread.** The seam serves every request on its own thread, and a connection is
   one session: shared by two handler threads it would make the two concurrent requests read the same
   transaction, so nothing could be refused by the layer. Per-thread connections are what turns "two
   concurrent requests" into two transactions against the same database.
2. **One transaction per request, with the snapshot taken at the moment the request begins.** The
   pre-check that names the machine reads that snapshot, so two requests that are genuinely concurrent
   name the same machine for the same slot — and that is exactly the point: the pre-check is allowed to
   be stale because it is not the guarantee. The commit is at the end of the request, so the second
   insert for the same `(machine_id, start_time)` is refused by the persistence layer — the UNIQUE index
   on PostgreSQL, the write conflict on the same slot on SQLite — and the loser's request writes nothing.

Nothing here is mocked, and nothing here decides the race: `src/repository.py` is the layer that
inserts under the constraint, and `src/app.py` is the seam that answers the refusal.
"""

import os
import sqlite3
import threading
from contextlib import contextmanager

POSTGRES = "postgres"
SQLITE = "sqlite"

DEFAULT_URL = "postgresql://quickwash:quickwash@127.0.0.1:5432/quickwash"

# The snapshot is what the request reads on: the state as it was when the request began. PostgreSQL can
# state that isolation level; SQLite takes the snapshot at the first read of the transaction, which is
# what `SNAPSHOT_PROBE` establishes immediately after BEGIN.
SNAPSHOT_SQL = {
    POSTGRES: "BEGIN ISOLATION LEVEL REPEATABLE READ",
    SQLITE: "BEGIN",
}
SNAPSHOT_PROBE = "SELECT 1"


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
                probe = psycopg.connect(url, connect_timeout=3)
            except Exception:
                # No server reachable from this checkout: fall back, never a mock.
                pass
            else:
                probe.close()
                return Database(lambda: psycopg.connect(url, connect_timeout=3), POSTGRES, url)

    if path is None:
        raise ValueError("the sqlite backend needs a file path")
    return Database(lambda: sqlite_connection(path), SQLITE, path)


def sqlite_connection(path: str):
    """A connection for one thread, with the transaction state driven by `Database.snapshot`."""
    connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    # WAL is what lets a reader and a writer live at the same time. In the rollback journal a reader holds
    # the lock the writer needs to commit, so the winner of a race could not commit at all and the loser
    # would be refused by a lock instead of by the constraint.
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


class Database:
    def __init__(self, factory, backend: str, target: str) -> None:
        self._factory = factory
        self.backend = backend
        self.target = target
        self._local = threading.local()
        self._connections: list = []

    @property
    def connection(self):
        """The connection of the thread using the database: one session, so one request."""
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self._factory()
            self._connections.append(connection)
            self._local.connection = connection
        return connection

    @property
    def in_transaction(self) -> bool:
        """Whether the calling thread is inside the transaction its request opened."""
        return bool(getattr(self._local, "open", False))

    @contextmanager
    def snapshot(self):
        """One request, one transaction, snapshot taken before the request decides anything.

        The order is what the race needs: the snapshot is established at the start of the request, the
        commit is at its end. Two concurrent requests then read the same state, name the same machine for
        the same slot, and the second insert is refused. A refusal writes nothing.
        """
        connection = self.connection
        connection.execute(SNAPSHOT_SQL[self.backend])
        connection.execute(SNAPSHOT_PROBE)
        self._local.open = True
        try:
            yield connection
            if self.in_transaction:
                connection.commit()
        except Exception:
            if self.in_transaction:
                connection.rollback()
            raise
        finally:
            self._local.open = False

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
        # Inside the request's transaction nothing commits statement by statement: the request commits
        # at its end, and until then the insert is not yet a fact another request can read.
        if not self.in_transaction:
            self.connection.commit()
        return count

    def rollback(self) -> None:
        """Roll back what the calling thread's transaction had written: the refusal writes nothing."""
        self.connection.rollback()
        self._local.open = False

    def close(self) -> None:
        for connection in self._connections:
            connection.close()
