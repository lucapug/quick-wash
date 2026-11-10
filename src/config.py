"""Seed configuration: tariffs, opening hours, machine inventory, buffers.

Configuration is data, not a screen (docs/spec.md, Application shape). The numbers here are the
signed addendum's where it disagrees with docs/spec.md: turnover buffer 10 minutes, cleaning
buffer 30 minutes (patch 2), OTP shown in-app with no email or SMS transport (patch 1).

Inventory is the pack's seed: 8 machines, 4 standard, 2 family, 2 quick (tests/conftest.py).
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
    "turnover_minutes": 10,
    "cleaning_minutes": 30,
    "idle_open_minutes": 15,
    "no_show_window_days": 30,
    "no_show_threshold": 2,
    "block_days": 7,
    "bookings_per_day": 2,
    "owner_email": "owner@quickwash.local",
    "otp_displayed_in_app": True,
}
