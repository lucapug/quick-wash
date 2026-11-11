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
    "owner_email": "owner@quickwash.local",
    "otp_displayed_in_app": True,
    # AC4: the one-time code is single-use and lives 10 minutes. Held as a number here, like every
    # other number in this project, so the seam can read it back (issue #5, AC 7).
    "otp_ttl_minutes": 10,
}
