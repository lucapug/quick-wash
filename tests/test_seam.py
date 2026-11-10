"""The seam test the issue provided, executed exactly as given.

tests/conftest.py is frozen byte-identical (the CI gate hashes it against the issue body), and
pytest does not collect tests from a conftest, so the provided test is imported here unedited and
run through the fixtures defined in tests/fixtures.py.

What this module adds is the contract itself: the eight paths every rule test in the backlog is
written against, the three fixtures, and the readable-failure mechanism.
"""

from tests import fixtures
from tests.conftest import SEAM_PATHS
from tests.conftest import test_seam_is_the_only_entry_point  # noqa: F401 — run exactly as provided

from src import app as backend

CONTRACT = [
    "POST /api/session",
    "GET /api/availability",
    "POST /api/bookings",
    "GET /api/bookings",
    "POST /api/lock/redeem",
    "POST /api/lock/reports",
    "GET /api/machines",
    "GET /api/incidents",
]


def test_the_seam_paths_are_the_contract_every_rule_test_uses():
    assert SEAM_PATHS == CONTRACT
    assert {f"{method} {path}" for method, path in backend.ROUTES} == set(CONTRACT)


def test_every_seam_path_answers_over_http(client, seed):
    """The contract is live: each path answers as an externally observable HTTP outcome."""
    ada = client.session("ada@example.com")
    responses = {}
    for entry in CONTRACT:
        method, path = entry.split(" ", 1)
        if method == "GET":
            responses[entry] = client.get(path, headers=ada.headers)
        elif path == "/api/session":
            responses[entry] = client.post(path, {"email": ada.email})
        elif path == "/api/bookings":
            responses[entry] = client.post(path, {"type": "quick", "start": "10:00"}, headers=ada.headers)
        elif path == "/api/lock/redeem":
            responses[entry] = client.post(path, {"code": "0000"})
        else:
            responses[entry] = client.post(path, {"code": "0000", "event": "cycle_started"}, headers=ada.headers)

    failed = {entry: response.text for entry, response in responses.items() if response.status_code >= 500}
    assert not failed, failed
    assert all(response.headers.get("content-type") == "application/json" for response in responses.values())


def test_conftest_exposes_exactly_the_three_fixtures():
    assert fixtures.exposed_fixtures() == sorted(["client", "seed", "clock"])


def test_the_clock_the_test_controls_is_the_clock_behind_the_seam(client, clock):
    assert client.clock is clock and client.app.clock is clock
    assert clock.advance(30) == clock.now()
    assert client.app.clock.now() == clock.now()


def test_the_seam_runs_on_a_real_database_never_a_mock(client, seed):
    assert seed["backend"] in ("postgres", "sqlite")
    assert client.app.repo.machine_counts() == seed["types"]


def test_a_failing_assertion_prints_the_http_response_body(client):
    """The mechanism the hook in tests/fixtures.py uses: the last response is recorded per test."""
    response = client.get("/api/availability")
    assert client.last_response is response
    assert fixtures.response_section(client) == f"GET /api/availability -> {response.status_code}\n{response.text}"


def test_the_session_is_the_same_login_reused_across_requests(client, seed):
    ada = client.session("ada@example.com")
    assert ada.token and ada.headers["Authorization"] == f"Bearer {ada.token}"
    booking = client.post("/api/bookings", {"type": "quick", "start": "10:00"}, headers=ada.headers)
    mine = client.get("/api/bookings", headers=ada.headers).json()["bookings"]
    assert booking.status_code == 201 and mine[0]["machine"] == booking.json()["booking"]["machine"]
    # the seam knows who is asking: a different login sees an empty list
    other = client.session("bruno@example.com")
    assert client.get("/api/bookings", headers=other.headers).json()["bookings"] == []
