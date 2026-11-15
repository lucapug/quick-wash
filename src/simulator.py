"""The device boundary: `washer-simulator`, in-process, with the two calls of the lock API.

The device is the thing standing in front of the machine. It has no view of the domain: it can only say
what it saw at the machine, and it says it through the two contract calls a real controller would use —
one for the redemption, one for each report. It is not a service, it is not a second writer of the state,
and it holds nothing beyond the facts it observed: no copy of the machine state, no booking, no repository,
no field for money (the payment is physical and outside the system, `docs/spec.md`, Device boundary).

The invariant this module is the guard of: **a report is a fact the device observed, never a fact it
invents**. A machine it never saw open cannot be reported as open; a cycle it never saw start cannot be
reported as finished; an open it already reported as started cannot be an idle open. A report the device
cannot ground in its own observation is not sent at all — it is refused here, at the device, before it
reaches the seam. The seam then answers the same thing on its own terms: the hop the attempted report names
is not in the R6 table, so a request that carries it is refused with 409 and nothing is written
(issue #13, AC3, and the pinned `tests/integration/test_device_reports_coverage.py`).

The rule the device acts on is not a copy of the rule: `idle_open_due` is the same predicate the seam
evaluates on every read, so the 15-minute bound cannot be reached twice, once by the device and once by the
read. The device reads it through `src/machine_states.py` and hands it the two instants it observed.

Nothing here is a protocol, a transport or a service of its own: the device is handed a transport function
and the clock behind the seam as dependencies, and the whole of its memory is the `observed` record.
"""

from datetime import datetime

from src import machine_states
from src.clock import Clock
from src.config import SEED

# AC1: in-process inside the backend, not its own service. The contract is exactly the two calls.
IN_PROCESS = True
CONTRACT = {"redeem": ("POST", "/api/lock/redeem"), "report": ("POST", "/api/lock/reports")}

# The events the lock API accepts from the device (R6's `DEVICE_EVENTS`, read from the same table the seam
# uses). `occupied` is not one of them: that report is a customer's claim about a machine, not a device fact.
REPORTS = ("cycle_started", "cycle_finished", "fault", "idle_open")

# The whole of the device's memory: the facts it observed at the machine, nothing else. No field for money.
OBSERVED_FIELDS = ("machine", "opened_at", "cycle_started_at", "cycle_finished_at", "trace")


class NotObserved(Exception):
    """A report the device has no observation to ground. It is not sent: the device cannot invent a fact."""

    def __init__(self, event: str, missing: str) -> None:
        super().__init__(f"the device cannot report {event}: it never observed {missing}")
        self.event = event
        self.missing = missing


def observed_by(sim) -> dict:
    """The device's memory as it stands: only the fields it is allowed to hold."""
    return {field: sim.observed[field] for field in OBSERVED_FIELDS}


def device_view(sim) -> dict:
    """The device as a reviewer reads it: the two calls, the in-process placement, the observed facts."""
    return {
        "in_process": IN_PROCESS,
        "contract": {name: f"{method} {path}" for name, (method, path) in CONTRACT.items()},
        "reports": sorted(REPORTS),
        "observed": observed_by(sim),
        "fields": list(OBSERVED_FIELDS),
    }


class WasherSimulator:
    """The device in front of one machine.

    Four things and nothing more: the transport it is handed (the contract, over HTTP), the clock behind
    the seam it is handed as a dependency, the configuration, and what it has observed. It cannot write a
    machine state: the only thing it writes is its own `observed`, and every state it names is written by
    `Application.transition` through the R6 table.
    """

    def __init__(self, transport, clock: Clock | None = None, config: dict | None = None) -> None:
        self.transport = transport
        self.clock = clock or Clock()
        self.config = config or SEED
        self.observed = {field: None for field in OBSERVED_FIELDS}

    # --- the two calls of the contract ----------------------------------------

    def redeem(self, code: str, headers: dict | None = None):
        """The keypad entry: the device's first call, and the only one that can tell it which machine it is.

        Nothing here moves a machine beyond the open the device actually saw. The count of tokens is data
        the booking carries, answered at the call; the device never assumes a cycle from it.
        """
        answer = self._send("redeem", {"code": code}, headers)
        body = answer.json()
        self.observed["trace"] = body.get("trace") or self.observed["trace"]
        if body.get("outcome") == "unlocked":
            self.observed["machine"] = body.get("machine")
            self.observed["opened_at"] = self.clock.now()
        return answer

    def report(self, event: str, headers: dict | None = None):
        """A fact the device saw, on the contract path, carrying the journey it belongs to.

        An event the lock API does not accept is refused by name (the device cannot invent an event), and an
        event it has no observation for is refused before anything is sent: the seam is never asked to
        perform a hop the device did not see.
        """
        if event not in REPORTS:
            raise ValueError(f"the lock API does not accept this device report: {event}")
        if not self.observed_event(event):
            raise NotObserved(event, self.missing_for(event))
        answer = self._send("report", {"machine": self.observed["machine"], "event": event}, headers)
        body = answer.json()
        if self.observed["trace"] is None:
            self.observed["trace"] = body.get("trace")
        field = f"{event}_at"
        if field in OBSERVED_FIELDS:
            self.observed[field] = self.clock.now()
        return answer

    # --- what the device can ground in its own observation ---------------------

    def observed_event(self, event: str) -> bool:
        """True when the device has an observation this report is about."""
        if event == "cycle_started":
            return self.observed["opened_at"] is not None
        if event == "cycle_finished":
            # The device cannot invent a cycle it never started: `finished` is the moment it names what it
            # saw stop, and it can only have seen it stop on a cycle it saw begin.
            return self.observed["cycle_started_at"] is not None
        if event == "idle_open":
            return self.idle_open_due()
        return self.observed["machine"] is not None

    def missing_for(self, event: str) -> str:
        return {
            "cycle_started": "the open",
            "cycle_finished": "the start of the cycle",
            "idle_open": "an open that never started a cycle",
        }.get(event, "the machine")

    def idle_open_due(self) -> bool:
        """The 15-minute bound, on the same predicate the seam evaluates, on the device's own facts.

        An open the device already reported as started is not a lost turn: the predicate answers False for a
        cycle it saw begin, so there is nothing for the device to send and nothing for the read to write.
        """
        return bool(machine_states.idle_open_due(self.observed["opened_at"], self.clock.now(), self.config,
                                                 self.observed["cycle_started_at"]))

    def observe(self):
        """The device acts on what it notices: it sends the report only when it has the fact behind it."""
        if not self.observed_event("idle_open"):
            return None
        return self.report("idle_open")

    # --- the transport, nothing else ------------------------------------------

    def _send(self, name: str, body: dict, headers: dict | None):
        method, path = CONTRACT[name]
        payload = dict(body)
        # The journey the call belongs to, carried on the call: the device carries the identifier, it does
        # not invent one.
        if self.observed["trace"] is not None:
            payload["trace"] = self.observed["trace"]
        return self.transport(method, path, payload, headers)

    def seen_at(self, field: str) -> datetime | None:
        """One observed instant, read through the observed set only."""
        if field not in OBSERVED_FIELDS:
            raise KeyError(field)
        return self.observed[field]