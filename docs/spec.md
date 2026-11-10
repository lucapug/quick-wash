# quick-wash

Token-based washing machine booking for an unattended laundromat.

Triage: `ready-for-agent` — this document is a specification only. No implementation, no scaffolding, no configuration is included or implied here.

---

## Problem Statement

A coin/token laundromat with eight washing machines and **no staff on site**.

**From the customer's side.** I arrive with a bag of laundry and cannot tell which machine is free, when one will free up, or whether the one I am standing in front of has just finished a cycle and has not been emptied yet. I queue in front of a machine, I lose the wait, and sometimes I leave without washing. If I do get a machine, I have no way to keep it: anyone can take it while I go back to the car to fetch the detergent. There is no reservation, no turn, no queue, and nobody watching.

**From the owner's side.** I have eight assets and no visibility into them. I do not know which machine is idle, which one is blocked by a customer who never came back, and which one is out of order until a customer complains in person — and there is nobody in the shop to complain to. A machine that stops responding takes its whole capacity out of the day silently. A customer who books nothing arrives, finds nothing free, and never comes back.

**Why existing booking apps do not fit.** Almost every booking product assumes two things this venue does not have: an employee who mediates the handover, and payment captured online. Here the payment is **physical tokens inserted into the machine by the customer, on the spot**, and the only human in the room is the customer. A reservation that cannot survive the customer actually standing at the machine with tokens in hand is decoration.

**Expected behaviour.** The system must tell me which machine I am going to and at what time, hold it for me until I arrive, let me open it with a code, and reflect what really happened at the machine — including the cases where what really happened is that something went wrong and there is no staff to fix it.

---

## Solution

**quick-wash** is a full-stack booking application for one unattended laundromat. It reserves **a cycle, not a time window**: the customer chooses a machine *type*, quick-wash assigns a specific machine and an explicit start time, and issues a **numeric unlock code** the customer types at the machine. The customer pays the machine in tokens at that moment; the application never handles money.

The application owns the *state of the machines* and is the only thing standing between an empty shop and an orderly one:

- It computes which cycles are actually possible (duration, opening hours, closing time).
- It assigns a machine and protects the slot against two customers arriving for the same machine.
- It talks to the machine controller through a **lock API** and learns what happened: door opened, cycle started, cycle finished, or the customer opened the machine and never started a cycle.
- It reassigns customers when a machine fails, including when the customer is already standing in front of it.
- It treats the unattended failure modes as first-class problems: no-shows, machines left full of somebody else's laundry, faults reported only by the next customer.
- It gives the remote owner a small panel to see and to close what the automation cannot.

The interface is in Italian. **All documentation is in English.**

---

## User Stories

### Finding out what is possible

1. As a customer, I want to see which washing machine types are free right now and in the next few hours, so that I can decide whether to come now or later.
2. As a customer, I want to see each type's cycle duration and token price before I choose, so that I do not book a 75-minute cycle when I have 40 minutes.
3. As a customer, I want availability shown per machine type, so that I do not have to know or care which physical machine I will get.
4. As a customer, I want only start times that can actually finish before closing time, so that I am never offered a cycle that the shop cannot honour.
5. As a customer, I want to know the shop's opening hours and which days it is closed, so that I do not try to book outside them.
6. As a customer, I want the earliest valid start time offered first, so that the common case takes one tap.
7. As a customer, I want to be told *why* a start time is unavailable (all machines busy, machine in maintenance, cycle would overrun closing), so that I understand the system instead of fighting it.
8. As a passers-by without an account, I want to read availability without signing in, so that I can decide whether to walk in.

### Booking

9. As a customer, I want to book a cycle by choosing a type and a start time, so that I have a guaranteed machine at a known hour.
10. As a customer, I want to be told exactly which machine I have been assigned, so that I can find it when I arrive.
11. As a customer, I want my booking to show the machine number, the start time, the expected end time and the tokens the machine will require, so that I arrive prepared.
12. As a customer, I want the assignment to be made at booking time rather than at arrival, so that there is no scramble in front of the machines at the booked hour.
13. As a customer, I want the machine kept for me until my grace window ends, so that a small delay does not cost me my turn.
14. As a customer, I want confirmation of my booking to be visible in the app immediately, so that I have no doubt the reservation exists.
15. As a customer, I want to see my current bookings and their status, so that I know what I still have to honour.
16. As a customer, I want to be refused politely with a list of valid alternative slots when my first choice cannot be honoured, so that I can fix it myself.
17. As a customer, I want a clear message when my booking fails because a machine type just became fully booked, so that I do not think the app is broken.

### Identity and access

18. As a customer, I want to sign in with my email and a one-time code, with no password to create or recover, so that using the app costs me under a minute.
19. As a customer, I want to be recognised again on my next visit without re-entering credentials each time, so that the app stays fast.
20. As a customer, I want my unlock code to be tied to my booking, so that nobody else can use it.
21. As a customer, I want the unlock code displayed in the app rather than sent by email or SMS, so that I do not depend on signal or inbox inside the shop.
22. As a customer, I want the unlock code displayed only inside my own booking and nowhere in a public view, so that it cannot be harvested from the availability page.

### Arriving at the machine

23. As a customer, I want the code to unlock the machine when I type it on the machine's keypad, so that I can load my laundry without waiting for anyone.
24. As a customer, I want the code to work from 10 minutes before my start time, so that I can load early if I arrive early.
25. As a customer, I want the code to stop working after my grace window with a message that says so, so that I understand I lost the turn rather than that the machine is broken.
26. As a customer, I want a code to be usable only once, so that a second customer cannot open the same machine with my code.
27. As a customer, I want an invalid or unknown code rejected clearly, so that a typo does not look like a system failure.
28. As a customer, I want to pay the machine with tokens on the spot, so that nothing about payment has to happen in the app.
29. As a customer, I want the app to tell me the required token count before I open the machine, so that I do not open it and then discover I am short.

### The cycle and leaving the machine

30. As a customer, I want my booking to move to *running* when the machine actually reports that a cycle started, so that the state reflects reality rather than a timer.
31. As a customer, I want to see when my cycle is expected to finish, so that I come back to unload at the right time.
32. As a customer, I want the machine to become free only when it is genuinely usable, so that I am not told a machine is available when it is full of someone else's laundry.
33. As the customer of the next cycle, I want to report that the machine I was assigned to is still full or dirty, so that the shop does not leave me standing there.
34. As the customer of the next cycle, I want reporting a blocked machine to get me an immediate reassignment to a free machine of the same type, so that my turn is not lost.
35. As a customer, I want a machine reported as still occupied to be taken out of circulation for cleaning, so that the same failure does not hit the next three customers.

### When the machine fails

36. As a customer, I want my booking to survive my machine breaking, so that I am punished for a fault I did not cause.
37. As a customer, I want to be moved to another free machine of the same type automatically, with a new code, so that I keep my time slot.
38. As a customer, I want to be notified when my machine is reassigned, with the new machine number, so that I do not go to the wrong one.
39. As a customer, I want to be told honestly when no machine of my type is free — booking cancelled, my turn refunded so I can rebook immediately — so that I am not left with a booking I cannot use.
40. As a customer who is already standing at a broken machine, I want an immediate reassignment rather than a support process, because there is no staff to ask.
41. As a customer, I want to report a machine as faulty only if I have or had a booking on it, so that the report mechanism cannot be abused to make a machine unavailable for someone else.
42. As a later customer, I want a machine in maintenance to be visibly unavailable, so that I am not assigned to it.

### Changing my mind

43. As a customer, I want to cancel a booking freely up to 15 minutes before it starts, so that plans can change.
44. As a customer, I want a late cancellation refused with an explanation, so that I know the machine is already committed.
45. As a customer, I want my cancelled slot to become bookable by others immediately, so that the shop is not blocked by my change of plans.
46. As a customer, I want to see the state of a booking I can no longer cancel, so that I know what will happen to it.

### Fairness of the queue

47. As a customer, I want a limit on how many bookings one person can hold in a day, so that one household cannot take a quarter of the shop.
48. As a customer, I want to know when I have reached that limit and when it resets, so that the rule is predictable rather than a mysterious error.
49. As a customer, I want the shop's availability protected from no-shows, so that the machine I could have used was not held for someone who never came.
50. As an honest customer, I want repeated no-shows to cost the offender something, so that free reservations do not destroy availability in a shop with nobody watching.
51. As a customer under a booking block, I want to be told clearly that I am blocked, until when, and why, so that I can correct my behaviour instead of abandoning the app.
52. As a customer who opened a machine and never started a cycle, I want that to be treated as a lost turn with the machine released quickly, so that the next customer is not locked out.

### The owner

53. As the owner, I want a status board showing every machine and its current state, so that I can see the shop from home.
54. As the owner, I want to put a machine into maintenance and take it back out, so that a known fault stops generating customer failures.
55. As the owner, I want to see the bookings attached to a machine before I take it out of service, so that I understand what I am breaking.
56. As the owner, I want to cancel or reassign a booking manually, so that the automation's decision can be overridden by someone who knows the shop.
57. As the owner, I want incidents (reassignments, cancellations, refunds, blocked machines) collected in one place, so that I can see what the shop suffered today.
58. As the owner, I want the owner panel protected by the same email-and-code sign-in, so that it is not open to customers.
59. As the owner, I want tariffs, opening hours and machine inventory to be configuration rather than screens I have to maintain, so that I spend no time on data entry.

### Operators and reviewers

60. As a reviewer of this project, I want to start the whole system with one command, so that I can evaluate it rather than assemble it.
61. As a reviewer, I want a deterministic way to make a machine fail, so that I can see the failure handling, the alert and the response with my own eyes instead of waiting for a random event.
62. As a reviewer, I want a demo seed of eight machines so that I can exercise the interesting cases immediately.
63. As a developer working on this project, I want the domain rules written as explicit acceptance criteria before the code, so that I know when the system is correct.
64. As a maintainer, I want a single entry point for testing the whole journey, so that a regression in the booking flow cannot hide behind passing unit tests.

---

## Implementation Decisions

### Domain model

- **One venue.** A single laundromat. No venue identifier on the domain objects, no multi-site abstraction, no branch hierarchy.
- **Seed inventory: 8 washing machines across 3 types.**
  - `standard` — 6 kg, 60-minute cycle, 4 tokens.
  - `family` — 8 kg, 75-minute cycle, 6 tokens.
  - `quick` — 30-minute cycle, 3 tokens.
- **Tariff and duration belong to the type, not to the individual machine.** A machine inherits its type's `cycle_minutes` and `tokens_required`. Per-machine pricing was explicitly rejected: it adds a field and an inconsistency to explain with no behavioural gain.
- **Opening hours:** 07:00–22:00, closed on Sundays. Held as seed/configuration, not editable through an admin screen.
- **Start times are quantised on a 15-minute grid.** Cycle durations are fixed per type; only the start time is discretised.

### Machine state machine

`available → reserved → unlocked → running → finished → available`

Side branches and terminal states:

- `maintenance` — reachable from `available`, `reserved`, `unlocked`, `finished`. A machine in `maintenance` cannot be assigned.
- `cleaning_required` — reachable from `finished` when the next customer reports the machine as still occupied; returns to `available` after the cleaning buffer.
- `expired` — a terminal state of a *booking* (not of a machine) when the code was never redeemed within the grace window.
- `idle_open` — an event, not a state: a machine reported `unlocked` with no `cycle_started` within 15 minutes. The booking is closed, the machine released, and an incident recorded.

Invalid transitions are rejected, not silently coerced (for example `running → available` without passing through `finished`).

### Rules (acceptance criteria, agreed before code)

| # | Rule | Behaviour |
|---|---|---|
| R1 | Real duration, not a fixed grid | A booking lasts `cycle_minutes` of its type. Valid only if `start + cycle_minutes ≤ closing time`. Last `quick` start 21:30, last `standard` 21:00, last `family` 20:45. |
| R2 | Opening hours honoured | Bookings accepted only within opening hours, on open days. A cycle that would overrun closing is refused, with the next valid slot offered. |
| R3 | Grace and no-show | The unlock code is valid from 10 minutes before start to 10 minutes after. After that: booking `expired`, machine `available`, code dead. |
| R4 | Cancellation window | Free cancellation up to 15 minutes before start. Refused after that, with the booking's current state shown. |
| R5 | No overbooking, race-protected | Two concurrent requests for the same type and slot never produce two bookings on one machine. The loser gets an error plus valid alternatives. Enforced by the persistence layer, not by a pre-check. |
| R6 | Declared state machine | All transitions documented; invalid transitions rejected. |
| R7 | Fault report constrained | Only a customer who has or had a booking on that machine may report it. The report drives `maintenance` and triggers reassignment of future bookings. |
| R8 | Reassignment | On `maintenance`, future bookings are reassigned to free machines of the same type, earliest-start-first, with a new code and a notification. Uncoverable bookings are cancelled with the turn refunded (immediate rebooking allowed) and an incident recorded. No booking may remain attached to a machine in `maintenance`. |
| R9 | No-show penalty | 2 no-shows in 30 days block new bookings for 7 days, with the block and its expiry shown to the customer. `idle_open` counts as a no-show for this counter. |
| R10 | Turnover | After `finished`, the machine stays unbookable for a fixed turnover buffer. The next assigned customer may report it as still occupied → `cleaning_required` plus immediate reassignment of that customer. |
| R11 | Per-customer limit | Maximum 2 bookings per customer per day, independent of overlap. The limit and its reset are visible to the customer. |

R9 and R11 exist because a reservation here is free and unpoliced: without them, availability in an eight-machine unattended shop collapses in a week.

### Identity

- **Email + one-time code. No password, no reset flow, no social login.** The one-time code establishes identity and grants the right to manage one's own bookings.
- Password hashing was deliberately excluded: it is a security surface the product does not need and that a reviewer cannot meaningfully test in ten minutes.
- Fully anonymous booking was deliberately excluded: it makes no-shows untraceable, which makes R9 impossible.
- **The unlock code is a second, distinct code.** It is a numeric code tied to a single booking, displayed only inside that booking in the app — not emailed, not SMS'd, not shown on any public availability view.

### Device boundary

- The application exposes a **lock API**: the machine controller calls it to redeem a code. Outcomes: `unlocked`, `expired`, `already_redeemed`, `unknown_code`. The API also accepts the device-side reports `cycle_started`, `cycle_finished`, `idle_open`, and machine fault.
- The unlock code is **numeric and typed on the machine keypad**, because a token washer already has a keypad. This was chosen over a QR scan: no inventing a reader, and redemption is trivially testable.
- **`washer-simulator` runs in-process inside the backend**, not as a separate container. This is a deliberate revision of the earlier decision to give the simulator its own service, taken because of the 14-hour budget (see Further Notes). It keeps the contract identical — one internal call for redemption, one for each device report — so the failure modes, the state transitions and the tests are unchanged, and the contract stays valid for a future real controller.
- The payment is physical and outside the system entirely. The system records `tokens_required` as data and infers nothing about money: `running` is driven by the device reporting `cycle_started`, never by a timer and never by an assumption that tokens were inserted.

### Application shape

- Full-stack: a web frontend for customers, a backend exposing the domain over HTTP plus the lock API, and a persistent relational database.
- **The customer-facing availability view is readable without signing in.** Booking and managing bookings require the email-and-code sign-in.
- **Owner panel: minimal only.** Machine status board, put a machine in and out of maintenance, view bookings attached to a machine, manually cancel or reassign a booking, and an incident list. No tariffs screen, no opening-hours screen, no machine registry UI, no occupancy reporting.
- The owner sign-in uses the same email-and-code mechanism as the customer, with an owner flag.
- Tariffs, opening hours and machine inventory are seed/configuration data.

### Observability shape

- One key user journey instrumented end to end — *booking → redeem → cycle start → cycle finish* — with structured logs, a metric of customer-blocked events, and a trace identifier shared by every log line and metric attached to that journey.
- No customer email, no unlock code, and no credential may appear in telemetry.
- Open decisions 2 and 3 in *Further Notes* (alerting, on-call responder) sit on top of this instrumentation; they are not yet decided.

---

## Testing Decisions

### What makes a test good here

A test asserts an externally observable outcome of a rule, never an internal call. "The second concurrent booking for the same machine and slot was refused and the response listed alternatives" is a test. "The availability service was called with the correct argument" is not. Every rule R1–R11 is expressible as one such assertion, because each was written as an acceptance criterion before the code.

### Seam

**One seam: the HTTP boundary of the backend.** It is the highest seam available in a greenfield system and it is the only seam integration tests will use. Through it, tests drive the whole journey — availability query, booking, code redemption by the simulated controller, `cycle_started`, `cycle_finished`, turnover buffer, fault, reassignment — against a real database, in the same shape a reviewer would exercise by hand.

Choosing this seam means the in-process simulator is *behind* it: tests interact with the device the way a real machine does, by calling the lock API, so the device boundary is exercised rather than bypassed.

Domain rules are asserted through the same seam: grace expiry, no-show penalty, per-day limit, race on the slot, `idle_open`, constrained fault report, turnover reporting. Unit tests are reserved for the genuinely pure pieces where a unit test is shorter and sharper than an end-to-end one:

- computing valid start times for a type given opening hours and cycle duration;
- computing the grace window of a booking;
- evaluating the no-show counter and its block expiry.

Anything that would require mocking the repository or the clock inside a unit test moves to the HTTP seam instead.

### What is tested per module

- **Booking domain** (assignment, slot validity, race protection, R1–R5, R11) — through the HTTP seam.
- **Machine lifecycle** (state machine, R6, `idle_open`, turnover and `cleaning_required`) — through the HTTP seam, driven by device reports.
- **Failure handling** (R7, R8) — through the HTTP seam, with a fault injected on demand.
- **Ownership and entitlements** (one-time code sign-in, customer can only touch own bookings, fault report constraint, owner-only panel) — through the HTTP seam.
- **Pure time and counter helpers** — unit tests.

Unit and integration tests must both run from a single command. Prior art: none, the repository is greenfield apart from the grading rubric.

---

## Out of Scope

- **Any online payment.** No payment gateway, no card, no wallet, no token top-up. Payment is physical, at the machine.
- **A token ledger or account balance.** No customer credit, no consumption history, no revenue reconciliation. `tokens_required` is descriptive data, not an accounting entry.
- **Real hardware.** No MQTT, no controller firmware, no device pairing, no vendor protocol. The in-process simulator is the contract's only implementer; the contract is what would survive integration with a real controller.
- **Multi-site, chains, per-venue pricing, cross-venue bookings.**
- **A complete owner console.** No tariff editing, no opening-hours editing, no machine registry, no reporting dashboards.
- **QR-based unlock.**
- **A staff role.** There is no staff in this shop; any design that quietly assumes one is a bug, not a feature.
- **Notifications outside the app** (email, SMS, push).
- **CI/CD at the highest grading tier** (automatic deploy to dev plus a separate manual production deploy) — explicitly traded away for the budget.
- **Machine capacity beyond type (kg), load sensors, water or energy telemetry.**
- **Dynamic pricing, loyalty, promotions, referral schemes.**
- **Anti-abuse beyond R9** (device fingerprinting, rate limiting as a product feature, IP reputation).

---

## Further Notes

### Grading rubric

The project is graded against `Rubric_aidevtools2026.html` — the DataTalksClub AI Dev Tools Zoomcamp 2026 final project rubric: **12 criteria, 24 points, 10 to pass**, documentation required in English, roughly 20 hours of work expected, two attempts allowed. It requires a frontend, a backend and a database; unit *and* integration tests; the whole system including the database containerised and startable with one command; a deployment reachable at a public URL; CI/CD; correlated metrics, traces and structured logs viewable in a UI with no customer data in telemetry; at least one alert; and an on-call agent that wakes on an alert and fixes the issue.

### Budget

The agreed budget is **~14 hours**, against the rubric's nominal ~20. That budget is what drove three decisions: the simulator placed in-process rather than as its own service; the owner panel cut to minimal; and the highest CI/CD tier dropped. Expected score at this budget, with the open items below left unresolved, is **13–14 of 24**.

### Open decisions (not settled — deliberately left open, not silently chosen)

1. **Are faults deterministic or random?** Recommendation: a deterministic trigger (a configuration switch or an owner-panel action that puts a named machine out of use on demand). A grading criterion nobody can demonstrate in a live demo does not earn its points, and a fault that only exists inside the integration tests does not exist in the system for the reviewer.
2. **Does an alert exist, and what does it measure?** Recommendation: the alert must fire on *customer impact*, not on system load — for example, a booking whose code cannot be redeemed because the machine controller is not responding, or a machine left `idle_open`. This criterion is worth 1 point and is the entry point to the next one.
3. **What is the on-call responder authorised to do?** Recommendation: act at the domain level — put the failing machine into `maintenance`, trigger R8 reassignment for the affected bookings, record the incident, and stop and escalate to the owner when no machine of the type is free. Acting at infrastructure level (restart a component and verify recovery) may be added, but code-changing and opening a pull request is not: it is the most spectacular option and the most fragile one at this budget.

These three are one chain — instrumentation, alert, responder — worth **3 of the 24 points**, and they fail together: a weak link zeroes all three.

### Rubric gaps this specification does not close on its own

- **Product Specification** requires *a publicly accessible task tracker whose tasks define acceptance criteria*, plus evidence that the agents used it. `spec.md` is the specification half; the tracker half does not exist yet — there is no repository and no tracker in this directory. R1–R11 are already phrased as acceptance criteria and can be lifted into tracker tasks directly.
- **Context Management** requires a project context file that also points to modular docs. Not yet created.
- **Agent Team Specification** requires defined agent roles and how they work together. Not yet defined; it is writing effort, not engineering effort, and it is currently unclaimed.

### Reconciliation of an internal tension

The interview settled the machine-assignment model as *type-based booking with app-side assignment to a specific machine*, while the physical reality described is *the customer walks to the machine they were told about and types a code*. These are consistent only if assignment is fixed at booking time and reassignment is a deliberate, notified event (R8). This specification takes that reading. The alternative — a code valid on any free machine of the type, first-come-first-served at the machine — was rejected: it creates a race for the last free machine that is not solvable well inside this budget, and a poorly solved race is exactly what an integration test exposes.
