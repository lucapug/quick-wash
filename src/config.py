"""Seed configuration: tariffs, opening hours, machine inventory, buffers.

Configuration is data, not a screen (docs/spec.md, Application shape). The numbers here are the
signed addendum's where it disagrees with docs/spec.md: turnover buffer 10 minutes, cleaning
buffer 30 minutes (patch 2), OTP shown in-app with no email or SMS transport (patch 1), one-time code
single-use and valid 10 minutes (issue #9, AC4). The code's TTL is read back over HTTP as the expiry the
sign-in response carries.

Inventory is the pack's seed: 8 machines, 4 standard, 2 family, 2 quick (tests/conftest.py).
The split is 4 + 2 + 2: the pack fixes the total at 8 but not the split, and R7/R8 reassignment to a
free machine of the same type needs at least two machines per type to be demonstrable while one is in
`maintenance`. Every number here is read back over HTTP (issue #5, AC 7): nothing is editable
through a screen, and no number is duplicated in a machine row.

Issue #24 adds the deterministic fault trigger as a key here, for the same reason as every other number:
the switch is configuration, not a screen, and it is read at startup. `fault_trigger_machine` names one
machine and its default is empty, so a normal run seeds an inventory with nothing broken — the demo is what
the reviewer asks for, not a state the system is in. It is held in the seed because the application reads
exactly two variables (`docs/deployment.md`, Environment variables): the switch is seed data, and the name
the issue writes in capitals is the key's name, not a third variable.
"""

SEED = {
    "machines": 8,
    "types": {"standard": 4, "family": 2, "quick": 2},
    "tariffs": {
        "standard": {"capacity_kg": 6, "cycle_minutes": 60, "tokens": 4},
        "family": {"capacity_kg": 8, "cycle_minutes": 75, "tokens": 6},
        "quick": {"capacity_kg": None, "cycle_minutes": 30, "tokens": 3},
    },
    "opening_hours": {"open": "07:00", "close": "22:00"},
    "closed_days": ["Sunday"],
    "grid_minutes": 15,
    "grace_minutes": 10,
    "cancel_window_minutes": 15,
    "turnover_buffer_minutes": 10,
    "cleaning_buffer_minutes": 30,
    "idle_open_minutes": 15,
    "no_show_window_days": 30,
    "no_show_threshold": 2,
    "block_days": 7,
    "bookings_per_day": 2,
    # R11 (issue #21): "per day" is the local shop day, not the UTC one, and the number is held here like
    # every other number in this project so it can be read back over HTTP. The shop runs on local hours
    # (07:00-22:00, closed Sunday); a UTC day would reset in the middle of a shop evening.
    "timezone": "Europe/Rome",
    "owner_email": "owner@quickwash.local",
    # Issue #24 (open decision 1, accepted as signed): the deterministic fault trigger. Empty means no
    # machine is out of use at startup; a code or a number names the machine the seed puts out of service
    # before the first request, on the same core a customer's report runs. Determinism is the point — a
    # grading criterion nobody can demonstrate in a live demo does not earn its points.
    "fault_trigger_machine": "",
    "otp_displayed_in_app": True,
    # AC4: the one-time code is single-use and lives 10 minutes. Held as a number here, like every
    # other number in this project, so the seam can read it back (issue #5, AC 7).
    "otp_ttl_minutes": 10,
}
