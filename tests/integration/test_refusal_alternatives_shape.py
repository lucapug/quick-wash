"""The shape of the 409 answer when the race is lost (issue #11 slice c, AC1-AC3).

The pinned test of this issue, `tests/integration/test_refusal_alternatives_ux.py`, describes a seed with
three machines of the `quick` type: one booked at 14:00 and two free for later slots. The pack pins two
(`tests/test_seam.py`, `tests/integration/test_seed_configuration.py`), and
`tests/integration/test_availability_reasons.py` pins that two customers can hold the same slot on two
machines of the same type — so with the seed as it is, the second request for a slot the type can still
give is not a loser: it books. What is asserted here is the part slice c owns, driven through the same
seam, on a race the layer actually decides.

The three things the slice owns, each one an externally observable outcome:

1. the alternatives are slots the shop can actually honour, earliest first, from the same type;
2. at most 3 of them (the Decision), and every one bookable — a machine of the type free at that point,
   not in `maintenance` (US42), not inside a buffer at that point, and inside the customer's own R11
   allowance, because a slot the customer cannot take is not an alternative a polite refusal may list;
3. the 15-minute grid of slice a.

Nothing is mocked: the client posts over 127.0.0.1, the repository is a real database, and the machines are
driven the way a real controller drives them, through the lock API.
"""

from datetime import datetime

from src import availability

THURSDAY = datetime(2026, 11, 12)


def at(client, hour, minute):
    client.clock.set(THURSDAY.replace(hour=hour, minute=minute))


def booked(client, who, start, type_key="quick"):
    response = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who.headers)
    assert response.status_code == 201, response.text
    return response.json()


def refused(client, who, start):
    response = client.post("/api/bookings", json={"type": "quick", "start": start}, headers=who.headers)
    assert response.status_code == 409, response.text
    return response.json()["alternatives"]


def the_race_is_lost_at_1400(client, event_on_the_second_machine):
    """Two customers hold the two machines of the `quick` type for the 13:30 turn. The first cycle has
    just finished, so at 14:00 M7 is inside the 10-minute turnover buffer (R10, patch 2); the second
    machine is reported at 14:00 and is therefore not free for that moment either — `occupied` puts it in
    `cleaning_required` for 30 minutes (US35), `fault` puts it out of circulation (R7, US42). So the
    request for 14:00 is the loser, and only the machine that can actually give a point is listed."""
    ada, bruno = client.session("ada@example.com"), client.session("bruno@example.com")
    first, second = booked(client, ada, "13:30"), booked(client, bruno, "13:30")
    assert {first["machine"], second["machine"]} == {"M7", "M8"}

    at(client, 13, 35)                                        # inside the grace window (R3)
    client.post("/api/lock/redeem", {"code": first["code"]})
    client.post("/api/lock/reports", {"code": first["code"], "event": "cycle_started"})
    at(client, 14, 0)
    client.post("/api/lock/reports", {"code": first["code"], "event": "cycle_finished"})
    reported = client.post("/api/lock/reports", {"machine": second["machine"], "event": event_on_the_second_machine},
                           headers=bruno.headers)
    assert reported.status_code == 200, reported.text
    return first, second, bruno


def test_the_loser_of_the_race_gets_bookable_alternatives_earliest_first(client, seed):
    the_race_is_lost_at_1400(client, "occupied")             # M8 out of circulation for 30' (US35)
    carla = client.session("carla@example.com")
    alts = refused(client, carla, "14:00")

    assert 0 < len(alts) <= availability.MAX_ALTERNATIVES == 3
    assert alts == sorted(alts, key=lambda a: a["start"]), "earliest first"
    assert all(a["type"] == "quick" for a in alts), "from the same type"
    assert all(a["start"].endswith(("00", "15", "30", "45")) for a in alts), "15' quantization"
    assert all(a["bookable"] for a in alts), "only slots the shop can actually honour are listed"
    # 14:00 + the 10' turnover buffer for one machine, 14:00 + the 30' cleaning buffer for the other.
    assert [a["start"] for a in alts] == ["14:15", "14:30"], alts
    for a in alts:
        assert client.post("/api/bookings", json={"type": "quick", "start": a["start"]},
                           headers=carla.headers).status_code == 201, "every listed slot is bookable"


def test_a_machine_in_maintenance_is_never_one_of_the_alternatives(client, seed):
    """US42 and R7: a machine out of circulation cannot serve a turn, so the only point the refusal can
    list is the one the machine still in circulation can give — and the seam honours it on that machine."""
    first, second, bruno = the_race_is_lost_at_1400(client, "fault")
    carla = client.session("carla@example.com")
    alts = refused(client, carla, "14:00")
    assert alts and all(a["bookable"] for a in alts), alts
    assert [a["start"] for a in alts] == ["14:15"], alts      # only M7 can give a point
    for a in alts:
        taken = client.post("/api/bookings", json={"type": "quick", "start": a["start"]}, headers=carla.headers)
        assert taken.status_code == 201, a
        assert taken.json()["machine"] == first["machine"], "never the machine in maintenance"
        assert client.get(f"/api/machines/{second['machine']}").json()["state"] == "maintenance"


def test_the_answer_never_lists_a_slot_the_customer_cannot_take(client, seed):
    """R11 is part of bookability: the count is the Decision's 3 bounded by the day's remaining allowance,
    so the UI in issue #22 never offers a tap the seam would then refuse. Two points are listable here,
    one is bookable by this customer."""
    dana = client.session("dana@example.com")
    booked(client, dana, "09:30", "standard")                # one of her two for the day, another type
    the_race_is_lost_at_1400(client, "occupied")

    alts = refused(client, dana, "14:00")
    assert 0 < len(alts) <= min(availability.MAX_ALTERNATIVES, 2 - 1), alts
    for a in alts:
        assert client.post("/api/bookings", json={"type": "quick", "start": a["start"]},
                           headers=dana.headers).status_code == 201
