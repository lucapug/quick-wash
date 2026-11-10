"""The three fixtures every rule test uses.

tests/conftest.py is the file provided in the issue and must arrive byte-identical (the CI gate
compares its sha256 against the issue body), so it cannot also hold the fixtures. This module
defines exactly the three the issue names — `client`, `seed`, `clock` — and pytest.ini loads it
through addopts while keeping `testpaths = tests` and `pythonpath = .`. The provided test is
executed unedited from tests/test_seam.py.

Nothing is mocked here: the client talks to a real HTTP server over 127.0.0.1 and the repository
runs on a real relational database. No service has to be started by hand and nothing leaves the
machine — PostgreSQL is used when it is reachable, otherwise the file-backed fallback in src/db.py.
"""

import sys
import tempfile
import threading
from datetime import datetime

import pytest

from src.app import Application
from src.clock import Clock
from src.db import connect
from src.server import serve
from tests.seam import SeamClient

# A Thursday, inside opening hours, so window rules have room to move.
START = datetime(2026, 11, 12, 9, 0)


@pytest.fixture
def clock() -> Clock:
    yield Clock(START)


@pytest.fixture
def client(clock: Clock):
    with tempfile.TemporaryDirectory() as folder:
        db = connect(path=f"{folder}/quickwash.db")
        app = Application(db, clock=clock)
        server, port = serve(app)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        seam = SeamClient(f"http://127.0.0.1:{port}")
        seam.app, seam.db, seam.clock = app, db, clock
        try:
            yield seam
        finally:
            seam.close()
            server.shutdown()
            server.server_close()
            db.close()


@pytest.fixture
def seed(client: SeamClient) -> dict:
    """The seeded configuration and the 8-machine inventory, read back from the database."""
    counts = client.app.repo.machine_counts()
    values = client.app.repo.settings()
    return {
        "machines": sum(counts.values()),
        "types": counts,
        "opening_hours": values["opening_hours"],
        "closed_days": values["closed_days"],
        "tariffs": values["tariffs"],
        "buffers": {"turnover_minutes": values["turnover_minutes"], "cleaning_minutes": values["cleaning_minutes"]},
        "owner_email": values["owner_email"],
        "backend": client.db.backend,
    }


def exposed_fixtures() -> list[str]:
    module = sys.modules[__name__]
    def is_fixture(value):
        marker = getattr(value, "_pytestfixturefunction", None) or getattr(value, "_fixture_function_marker", None)
        return marker is not None
    return sorted(name for name in dir(module) if is_fixture(getattr(module, name)))


def response_section(client) -> str | None:
    """The last HTTP response of a test, as the failure report shows it."""
    response = getattr(client, "last_response", None) if client is not None else None
    if response is None:
        return None
    return f"{response.request} -> {response.status_code}\n{response.text}"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """A failing assertion prints the HTTP response body: the failure reads as an outcome."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    section = response_section(item.funcargs.get("client"))
    if section and hasattr(report.longrepr, "addsection"):
        report.longrepr.addsection("HTTP response body", section)
