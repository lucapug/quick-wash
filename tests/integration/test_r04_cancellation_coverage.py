"""What the three tests of issue #15 (R4) cannot show on their own.

`tests/integration/test_r04_cancellation.py` is the file the issue provides and it runs byte-identical:
one test per behaviour — the boundary minute is free, the minute after it is refused, the slot is
bookable again at once. What this file pins is the rest of the same seven criteria, each as an
externally observable HTTP outcome:

- **the boundary as a pair**, not as a single point: the minute at `start - 15` and the minute at
  `start - 14`, on two bookings taken at the same hour, so the decision (`now <= start - 15`, inclusive)
  is what answers and not a rounding;
- **the explanation** US44 asks for: the refusal states the cutoff in minutes, in the copy, not only as a
  number the client could have been given;
- **the refusal writes nothing**: the booking keeps its state, the machine keeps the state the booking
  holds it in, and no incident is recorded for an action that was refused;
- **no buffer on a cancellation**: the turnover buffer stays the hop that follows a cycle actually run
  (R10), so the machine is read free at the same moment the request is answered;
- **a cancellation is not a no-show** (R9): the counter is still empty after two cancellations, and the
  customer can still book;
- **the state of a booking that can no longer be cancelled is still readable** (US46), and the
  cancellation itself belongs to the owning customer only (issue #12).

Through the seam only: no repository call, no internal function, no mock other than the clock the
application is given as a dependency (docs/spec.md, Testing Decisions).
"""


def booked(client, who, type_key, start) -> dict:
    """A booking created by `who`, as the response that names it."""
    created = client.post("/api/bookings", json={"type": type_key, "start": start}, headers=who)
    assert created.status_code == 201, created.text
    return created.json()


# --- AC1: the boundary minute, read as a pair -----------------------------------------------

def test_the_boundary_minute_is_free_and_the_minute_after_it_is_refused(client, clock):
    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    # Two bookings for the same hour, on two machines of the type, so the only difference between the
    # two requests below is the minute the clock is on.
    on_the_cutoff = booked(client, anna, "standard", "11:00")
    one_minute_after = booked(client, beth, "standard", "11:00")

    clock.set("10:45")          # `start - 15`: the decision is inclusive, so this one is still free
    assert client.post(f"/api/bookings/{on_the_cutoff['id']}/cancel", headers=anna).status_code == 200

    clock.set("10:46")          # `start - 14`: the refusal has to be observable, not arguable
    refused = client.post(f"/api/bookings/{one_minute_after['id']}/cancel", headers=beth)
    assert refused.status_code == 409, refused.text
    assert refused.json()["minutes_to_start"] == 14
    assert refused.json()["state"] == "reserved"    # unchanged: the refusal wrote nothing


def test_the_refusal_states_the_cutoff_in_minutes_as_an_explanation(client, clock, seed):
    carl = client.session("carl@example.com")
    booking = booked(client, carl, "standard", "12:00")
    clock.set("11:50")          # ten minutes before start: past the window

    refused = client.post(f"/api/bookings/{booking['id']}/cancel", headers=carl)
    assert refused.status_code == 409, refused.text
    message = refused.json()["message"]
    assert "15" in message and "minuti" in message, message
    assert refused.json()["cutoff_minutes"] == 15

    # A refusal is a decision, not a write: the booking is still his and still in the state shown, the
    # machine is still reserved for it, and nothing was recorded for an action he was not allowed to take.
    read = client.get(f"/api/bookings/{booking['id']}", headers=carl)
    assert read.status_code == 200 and read.json()["booking"]["state"] == "confirmed", read.text
    assert client.get(f"/api/machines/{booking['machine']}").json()["state"] == "reserved"
    owner = client.session(seed["owner_email"])
    assert [row["kind"] for row in client.get("/api/incidents", headers=owner).json()] == []


# --- AC3 and AC4: the machine is read free at the moment of the request ---------------------

def test_no_buffer_is_applied_to_a_cancellation(client, clock, seed):
    anna = client.session("anna@example.com")
    booking = booked(client, anna, "quick", "16:00")
    machine = booking["machine"]

    clock.set("15:00")          # an hour before start: inside the window, and inside the read window
    assert client.post(f"/api/bookings/{booking['id']}/cancel", headers=anna).status_code == 200

    row = client.get(f"/api/machines/{machine}").json()
    assert row["state"] == "available"
    assert row["buffer_minutes"] is None, "the buffer is R10's hop after a cycle actually run"
    assert row["assignable"] is True
    # The public view answers on the same predicate: the point the cancelled booking held is offered
    # again, with no reason attached to it.
    slots = client.get("/api/availability?window_hours=4&type=quick").json()["types"]["quick"]["slots"]
    point = [slot for slot in slots if slot["start"] == "16:00"]
    assert point and point[0]["available"] is True and point[0]["reason"] is None, slots


def test_a_cancelled_booking_never_leaves_the_machine_reserved(client, clock, seed):
    anna = client.session("anna@example.com")
    booking = booked(client, anna, "family", "13:00")
    assert client.get(f"/api/machines/{booking['machine']}").json()["state"] == "reserved"

    assert client.post(f"/api/bookings/{booking['id']}/cancel", headers=anna).status_code == 200
    row = {m["machine"]: m for m in client.get("/api/machines", headers=client.session(seed["owner_email"]).headers).json()["machines"]}[booking["machine"]]
    assert row["state"] == "available"
    # US55 reads the bookings attached to a machine before it is taken out of service: a cancelled
    # booking is not one of them, so nothing is left holding the machine.
    assert row["bookings"] == []


# --- AC5 and AC6: the state of a booking she can no longer cancel is still hers to read ------

def test_a_late_booking_is_still_read_by_the_customer_it_belongs_to(client, clock):
    anna = client.session("anna@example.com")
    dani = client.session("dani@example.com")
    booking = booked(client, anna, "standard", "14:00")

    clock.set("13:46")          # fourteen minutes before start: no longer cancellable
    refused = client.post(f"/api/bookings/{booking['id']}/cancel", headers=anna)
    assert refused.status_code == 409, refused.text

    # US46: the refusal does not take the read away with it. She is shown what will happen to it.
    read = client.get(f"/api/bookings/{booking['id']}", headers=anna)
    assert read.status_code == 200, read.text
    assert read.json()["booking"]["state"] == refused.json()["booking_state"]
    assert client.get("/api/bookings", headers=anna).json()["bookings"][0]["id"] == booking["id"]

    # AC6: the window does not make a stranger entitled. The gate is read before the window, so a
    # caller who holds the id is answered with the entitlement, not with the cutoff.
    assert client.post(f"/api/bookings/{booking['id']}/cancel", headers=dani).status_code == 403
    assert client.post(f"/api/bookings/{booking['id']}/cancel").status_code == 401


# --- AC7: a turn given back is not a turn lost -----------------------------------------------

def test_cancellations_do_not_enter_the_no_show_counter(client, clock, seed):
    anna = client.session("anna@example.com")
    for start in ("10:00", "11:00"):
        booking = booked(client, anna, "quick", start)
        assert client.post(f"/api/bookings/{booking['id']}/cancel", headers=anna).status_code == 200

    # Two no-shows inside thirty days would have blocked her for seven (R9). Two cancellations do not:
    # the counter is still empty, so the next booking is answered, and the read still says so.
    list_read = client.get("/api/bookings", headers=anna).json()
    assert list_read["block"]["blocked"] is None, list_read
    third = client.post("/api/bookings", json={"type": "quick", "start": "12:00"}, headers=anna)
    assert third.status_code == 201, third.text

    owner = client.session(seed["owner_email"])
    kinds = [row["kind"] for row in client.get("/api/incidents", headers=owner).json()]
    assert sorted(kinds) == ["cancellation", "cancellation"], kinds
    assert "no_show" not in kinds
