"""`washer-simulator`: the device, in-process inside the backend, reached only through the lock API.

The earlier decision gave the simulator its own service; the pack revises it (docs/spec.md, Device
boundary) because of the 14-hour budget. What the revision must not change is the contract, and this
module is where that is held: the simulator has no service of its own and no transport of its own — it is
a function call away from the seam, and it can reach the backend through **exactly two calls**, the two
the lock API fixes: one for the redemption, one for each report. The shape of a call is the same one a
real controller would use, so the failure modes, the state transitions and the tests are unchanged and
the contract stays valid for the machine that will one day replace the simulator.

Two things make it a device rather than a second writer of the domain:

1. **It holds only what it observed at the machine** (`OBSERVED_FIELDS`): the machine it is standing in
   front of, the moment it observed the open, the moments it observed a start and a finish, and the
   journey identifier its own redemption answer gave it. It has no copy of the machine state, no booking,
   no repository and no field for money. `Application.transition` is the only writer of a machine state
   and it consults the R6 table; the device cannot reach either. It names what it saw and the domain
   answers with the declared hop.
2. **It cannot report what it did not observe.** A cycle that never started cannot be reported as
   finished: the device is not allowed to invent a fact, and that is what makes `running` and `finished`
   the outcome of a report rather than of a timer or of an assumption that tokens were inserted. Payment
   is physical and outside the system entirely, so there is no ledger here and nothing to put in one.

The journey trace (issue #25) is carried, not invented: the redemption answer names the identifier, the
device keeps it, and every report it sends carries it back, so every device call and every metric attached
to the journey reads as the same journey. The identifier is hashed from an internal id and is letters-only,
so it can never read as one of the two codes (`src/telemetry.py`), and the device never has a credential to
carry — the guard in the recorder is what keeps it that way.

The clock is a dependency handed to it, never something it mocks: it measures the idle time from the moment
it observed the open, and the 15-minute rule it acts on is `machine_states.idle_open_due` — the same
predicate the seam evaluates at report time and at every read of the machine state, so the device and the
domain cannot drift on the bound, and the rule needs no scheduler to be observable.
"""

from datetime import datetime

from src import machine_states
from src.clock import Clock
from src.config import SEED

# The contract, in exactly two entries: one call for the redemption, one call per report. Nothing else in
# the backend is reachable from here, and these are two of the eight entries tests/conftest.py pins, so a
# real controller and the simulator are the same caller on the same path.
CONTRACT = {"redeem": ("POST", "/api/lock/redeem"), "report": ("POST", "/api/lock/reports")}

# The device-side reports the lock API accepts (docs/spec.md, Device boundary): the two cycle events, the
# idle open, and the fault. They are events, not states — the device names what it observed, the table
# decides the hop. `occupied` is not in the list: that report is a customer's claim (R10, US33), not a
# fact the device observed.
REPORTS = ("cycle_started", "cycle_finished", "idle_open", "fault")

# What the device knows. Facts it observed at the machine, and nothing else — no machine state, no booking,
# no repository, no token field: the device does not know who booked and it cannot know whether anything
# was paid.
OBSERVED_FIELDS = ("machine", "opened_at", "cycle_started_at", "cycle_finished_at", "trace")

# The device runs in the same process as the backend (docs/spec.md, Device boundary): there is no second
# thing to start, and the record of that decision is this line.
IN_PROCESS = True

# A call is `transport(method, path, body, headers)` — the seam, and only the seam.
Transport = callable


class NotObserved(Exception):
    """A report the device did not observe. It is refused here, before it can become a domain fact."""

    def __init__(self, event: str) -> None:
        super().__init__(f"the device cannot report {event}: it never observed it")
        self.event = event


class WasherSimulator:
    def __init__(self, transport, clock: Clock | None = None, config: dict = SEED) -> None:
        if not callable(transport):
            raise TypeError("the simulator reaches the backend only through the contract transport")
        self.transport = transport
        self.clock = clock or Clock()
        self.config = config
        self.observed = {field: None for field in OBSERVED_FIELDS}

    # --- the two calls of the contract -------------------------------------------------

    def redeem(self, code: str, headers: dict | None = None) -> object:
        """One call for the redemption: the keypad entry, and nothing else."""
        response = self._call("redeem", {"code": code, "trace": self.observed["trace"]}, headers)
        payload = self._payload(response)
        # The device records what its own call answered: the machine it is standing in front of, the moment
        # the door opened, the journey the answer named. The code it typed is not kept — it is a credential,
        # and the device has no reason to remember one.
        if isinstance(payload, dict):
            self.observed["machine"] = payload.get("machine") or self.observed["machine"]
            self.observed["trace"] = payload.get("trace") or self.observed["trace"]
            if payload.get("outcome") == "unlocked":
                self.observed["opened_at"] = self.clock.now()
        return response

    def report(self, event: str, machine: str | None = None, headers: dict | None = None) -> object:
        """One call per report. The body is what a controller sends: machine, event, journey, nothing more."""
        if event not in REPORTS:
            raise ValueError(f"the device cannot send {event}: the lock API accepts {sorted(REPORTS)}")
        if event == "cycle_finished" and self.observed["cycle_started_at"] is None:
            raise NotObserved(event)
        target = machine or self.observed["machine"]
        response = self._call("report", {"machine": target, "event": event, "trace": self.observed["trace"]},
                              headers)
        self._record(event, target)
        return response

    # --- what the device can decide on its own -----------------------------------------

    def idle_open_due(self) -> bool:
        """The rule, read once: the open it observed is older than the bound and no cycle started."""
        return machine_states.idle_open_due(self.observed["opened_at"], self.clock.now(), self.config)

    def observe(self, headers: dict | None = None) -> object | None:
        """The device's own read: it fires `idle_open` when the open it observed reached the rule.

        No timer and no job: the device reports when it is looked at, on the clock it was handed, and the
        rule is the same predicate the seam evaluates at every read of the machine state. That is what keeps
        the 15-minute rule observable through the seam rather than through a scheduler a test cannot wait
        for — the spec forbids mocking the clock inside a unit test, so the outcome has to come from outside.
        """
        if self.observed["opened_at"] is None or self.observed["cycle_started_at"] is not None:
            return None
        if not self.idle_open_due():
            return None
        return self.report("idle_open", headers=headers)

    # --- the calls themselves ----------------------------------------------------------

    def _call(self, name: str, body: dict, headers: dict | None):
        method, path = CONTRACT[name]
        return self.transport(method, path, body, headers)

    def _record(self, event: str, machine: str) -> None:
        """The observed facts, in the order they were observed. Only `observed` is written here."""
        self.observed["machine"] = machine
        if event == "cycle_started":
            self.observed["cycle_started_at"] = self.clock.now()
        if event == "cycle_finished":
            self.observed["cycle_finished_at"] = self.clock.now()

    def _payload(self, response) -> dict:
        return response.json() if hasattr(response, "json") else (response if isinstance(response, dict) else {})

    def observed_view(self) -> dict:
        """The device's whole memory, read from outside: the observed facts and nothing else."""
        return dict(self.observed)


def device_view(simulator: WasherSimulator) -> dict:
    """The device as the reviewer can read it: the two calls it can make, what it holds, what it reports."""
    return {
        "in_process": IN_PROCESS,
        "contract": {name: f"{method} {path}" for name, (method, path) in CONTRACT.items()},
        "reports": list(REPORTS),
        "observed": list(OBSERVED_FIELDS),
        "journey": simulator.observed["trace"],
    }


def now_of(simulator: WasherSimulator) -> datetime:
    """The instant the device measures from: the clock it was handed, not one it made up."""
    return simulator.clock.now()
