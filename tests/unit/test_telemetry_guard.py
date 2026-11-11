"""The telemetry guard (issue #9, AC3): the pure piece that makes "no credential in telemetry" an
assertion rather than a promise.

Two rules, both pure: the recorder never takes a body (a credential arrives in a body), and every line
it writes is guarded before it is stored or printed. It refuses rather than redacts — a redacted
credential is still a credential that got into a log line. The HTTP side of the same invariant is
`tests/integration/test_otp_identity.py`, which reads the lines back through the seam.
"""

from datetime import datetime

import pytest

from src.clock import Clock
from src.telemetry import CredentialInTelemetry, Telemetry

START = datetime(2026, 11, 12, 9, 0)


def recorder(limit=50):
    lines = []
    return Telemetry(clock=Clock(START), limit=limit, emit=lines.append), lines


def test_the_recorder_refuses_a_line_that_would_carry_a_credential():
    telemetry, printed = recorder()
    for detail in ("code 1001 redeemed", "otp 483920 shown in-app", "anna@example.com signed in"):
        with pytest.raises(CredentialInTelemetry) as error:
            telemetry.record("POST", "/api/lock/redeem", 200, detail=detail)
        assert error.value.field == "detail"
    assert telemetry.recent() == [] and printed == []      # nothing stored, nothing printed


def test_the_recorder_never_takes_a_body_and_logs_the_path_without_its_query():
    telemetry, printed = recorder()
    line = telemetry.record("GET", "/api/availability?window_hours=4", 200)
    assert sorted(line) == sorted(["event", "method", "path", "status", "at", "trace"])
    assert line["path"] == "/api/availability"
    assert printed == [line]


def test_every_line_and_metric_of_one_journey_shares_one_trace():
    telemetry, printed = recorder()
    telemetry.record("POST", "/api/bookings", 201, event="booking", journey=7)
    telemetry.record("POST", "/api/lock/redeem", 200, event="redeem", journey=7)
    telemetry.record("POST", "/api/lock/reports", 200, event="report", journey=7)
    telemetry.count("customer_blocked_total", journey=7)
    assert len({line["trace"] for line in printed}) == 1
    assert printed[0]["trace"].startswith("t-")           # hashed from an internal id, never a code
    assert telemetry.metrics["customer_blocked_total"] == 1


def test_the_read_returns_the_recent_lines_and_the_metric():
    telemetry, _ = recorder(limit=2)
    for status in (200, 201, 204):
        telemetry.record("GET", "/api/availability", status)
    assert [entry["status"] for entry in telemetry.recent()] == [201, 204]
    view = telemetry.view()
    assert [entry["status"] for entry in view["entries"]] == [201, 204]
    assert view["metrics"] == {"customer_blocked_total": 0}
