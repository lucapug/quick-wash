
from concurrent.futures import ThreadPoolExecutor

def test_two_concurrent_bookings_for_one_slot_yield_exactly_one_booking(client, seed):
    def book(headers):
        return client.post("/api/bookings", json={"type": "quick", "start": "14:00"}, headers=headers)

    anna = client.session("anna@example.com")
    beth = client.session("beth@example.com")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(book, [anna, beth]))

    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409]
    loser = [r for r in responses if r.status_code == 409][0]
    assert loser.json()["alternatives"], "loser must be offered valid alternatives"
    booked = [r for r in responses if r.status_code == 201][0]
    machine = booked.json()["machine"]
    # The persistence layer, not a pre-check, is the guarantee: one machine, one slot.
    assert client.get(f"/api/machines/{machine}").json()["state"] == "reserved"
    assert client.get("api/bookings?machine=" + machine).json()[0]["id"] == booked.json()["id"]
