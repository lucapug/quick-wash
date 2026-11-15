# quick-wash

Token-based washing machine booking for one unattended laundromat: eight machines, no staff on site.
quick-wash reserves a cycle, not a time window — it assigns a specific machine and an explicit start
time, issues a numeric unlock code the customer types on the machine keypad, and records what really
happened at the machine (no-shows, faults, cleaning). The application never handles money: payment is
physical, in tokens, at the machine.

This page describes the system **as it is today**, not as the specification intends it to be. The
difference between the two is stated in [Not built today](#not-built-today).

## What is built

Everything that exists is the domain behind one HTTP seam, its persistence layer and its tests. The
interface language is Italian (the copy is in the responses the seam answers with); no front-end pages
are built.

| Area | Module | What it does today |
|---|---|---|
| Race-protected assignment | `src/repository.py`, `src/db.py` | Assignment happens at booking time on a specific machine. The guarantee is the persistence layer, not a pre-check: one unique index on `machine_id` + `start_time`, one transaction per request, one connection per thread. The loser is refused with 409 and the answer carries at most three alternatives it can actually take (`src/alternatives.py`). |
| Valid start times | `src/domain/time.py`, `src/availability.py` | Real duration per type (standard 60 min / 4 tokens, family 75 / 6, quick 30 / 3), 15-minute grid, cycles that would overrun closing refused with the fixed refusal vocabulary; the public view is per type and never names a machine, a customer or a code, and it is readable without a session. |
| Unlock code and grace window | `src/rules.py`, `src/app.py` | Numeric code tied to one booking, usable once, valid from 10 minutes before start to 10 minutes after. Past the window: booking `expired`, machine released through the declared hop, code dead, no-show counted. Expiry is evaluated at redemption and at every read — there is no scheduler. |
| Buffers (R10, addendum patch 2) | `src/machine_states.py`, `src/config.py` | Turnover buffer **10 minutes** after `finished`, cleaning window **30 minutes** in `cleaning_required`, both held as data in the seed and read back over HTTP; a repeat report restarts the window without inventing a state. |
| Cancellation window (R4) | `src/cancellation.py` | Free up to 15 minutes before start; after that the request is refused and the booking's current state is shown. |
| No-show counter (R9) | `src/domain/counters.py` | 2 no-shows in 30 days block new bookings for 7 days, with the reason and the expiry visible on the customer's own read; `idle_open` counts on that counter. |
| Daily limit (R11) | `src/daily_limit.py` | 2 bookings per customer on the shop's local day (`Europe/Rome`), counted on live bookings only; a refunded turn gives its seat back. |
| State machine (R6) | `src/machine_states.py` | The declared hops live in one table; `Application.transition` is the only writer of a machine state, and a hop the table does not declare is rejected with 409 naming the attempted transition, not coerced. |
| Device seam | `src/simulator.py` | `washer-simulator` runs in-process. It has no view of the domain and reports only what it observed: a machine it never saw open cannot be reported open, a cycle it never saw start cannot be reported finished. A report it cannot ground is never sent. |
| Identity | `src/identity.py` | Email + one-time code, no password and no reset flow. The one-time code is shown in-app immediately after the sign-in request (addendum patch 1): there is no email or SMS transport. It is stored hashed with its expiry, single-use, 10-minute TTL; the session token is opaque. |
| Entitlements | `src/entitlements.py` | A customer can read only her own bookings; a fault report is allowed only for someone who has or had a booking on that machine; the owner panel is closed to customers. A refusal writes nothing. |
| Fault report and reassignment (R7, R8) | `src/faults.py` | The accepted report drives `maintenance` through the declared hop, then the pass moves every turn still owed to the lowest-numbered free machine of the type, earliest start first, with a new code and a notification naming the new machine; what nothing of the type can cover is cancelled and refunded as the right to rebook. |
| Telemetry | `src/telemetry.py` | Structured lines for the key journey, one metric of customer-blocked events, a trace identifier shared by every line of a journey. The guard refuses rather than redacts: no email, no unlock code, no one-time code, no credential can enter a line. |
| Notifications | `src/notifications.py` | Inside the app only — no email, no SMS, no push. A notification belongs to the customer the booking belongs to. |
| Owner panel | `src/app.py` | Status board, machine list, incident list, maintenance toggle, manual cancellation — all gated on the owner flag before anything is read or written. |
| Tests | `tests/` | Unit tests reserved for the three pure pieces; integration tests drive the whole journey through the HTTP boundary against a real database. |

## Not built today

Stated as facts, not as intentions:

- **The alert chain and the on-call responder do not exist.** Open decisions 1-3 are accepted as
  signed (deterministic fault trigger, alert on customer impact, domain-level responder), but only the
  instrumentation half is implemented (`src/telemetry.py`). Nothing alerts and nobody is paged. The
  chain is worth 5/24 (2 + 1 + 2), which is what moves the realistic ceiling to 19/24; the base without
  it is 16 and the user target is 14, against a pass of 10.
- **There is no customer front-end and no telemetry UI.** The rubric asks for a viewable UI; today the
  reviewer reads the telemetry lines through the seam, not through a dashboard.
- **Deployment and CD are out of scope** (addendum patch 3): no public URL, no continuous deployment.
  The in-scope compensation is CI tier 1 on every pull request plus the deployment steps written in the
  documentation.
- **The one-command start does not include the database.** The compose file in this repository is the
  isolated lab topology (the egress gate and the agent container), not the running application: it
  declares no database service and no service that starts the backend. `src/db.py` prefers PostgreSQL
  through `QW_DATABASE_URL` and falls back to a file-backed SQLite database only when a path is given,
  so `python3 -m src.server` needs a reachable database. What runs the system end to end today is the
  test client, which starts the real HTTP server on 127.0.0.1 and the repository on a real relational
  database.
- **CI is tier 1 only**: the pytest gate on every pull request on the self-hosted factory runner, plus
  the sha256 tamper-check of the tests supplied in an issue. No deploy step.

## Quickstart

The quickstart is the devcontainer plus its compose file. Nothing below is promised beyond what the
repository contains.

```bash
# 1. the isolated lab: egress gate + the container the work happens in
cd .devcontainer
docker compose up          # or: devcontainer up, then open the workspace

# 2. inside the container — the single test command
python3 -m pytest -q

# 3. the backend process, only when a database is reachable
export QW_DATABASE_URL=...          # PostgreSQL, or install psycopg
python3 -m src.server               # listens on 127.0.0.1, PORT defaults to 8000
```

Step 2 is the command that exercises the whole system today: real HTTP, real relational database,
nothing mocked, nothing leaving the machine. Step 3 is the same application as a process; without a
reachable database it refuses to start rather than pretending.

The seed the tests read is the pack's inventory: 8 machines, 4 standard + 2 family + 2 quick, opening
07:00-22:00, closed on Sundays, 15-minute grid, 10-minute grace, 15-minute cancellation window, 10 and
30 minutes of buffers, 2 bookings per day. Every number is configuration, read back over HTTP, never a
screen.

## The seam

One seam: the HTTP boundary of the backend. Integration tests assert externally observable outcomes,
never internal calls. The eight contract entries `tests/conftest.py` pins (paths rooted at `api/`) are
the entry points every rule test is written against: `POST api/session`, `GET api/availability`,
`POST api/bookings`, `GET api/bookings`, `POST api/lock/redeem`, `POST api/lock/reports`,
`GET api/machines`, `GET api/incidents`. Reads that belong to an entry (one machine, one booking, a
report on one machine, the verification of a code, the telemetry read, the customer's own view, the
notifications) are patterns on those entries, so the contract stays exactly eight.

The suite runs with one command: `pytest` (`pytest.ini` sets `testpaths = tests` and `pythonpath = .`
and loads `tests/fixtures.py` through `addopts`, because `tests/conftest.py` is a supplied file that
cannot also hold the fixtures). It collects 249 tests: 236 pass, 12 are recorded contradictions carried
as xfail markers with the reason written next to them, and 1 reports XPASS. The supplied files are
never adjusted to make the gate green — where a supplied test contradicts the pack, the contradiction
is recorded and needs a human decision. Unit tests stay on the three pure pieces only: valid start
times, the grace window, the no-show counter and its block expiry.

## How it was built

The work is the agent team loop documented in [docs/agent-team-spec.md](docs/agent-team-spec.md) and
run on the tracker under the conventions of [docs/tracker.md](docs/tracker.md): one issue = one PR,
branch `feat/issue-<N>`, commit subject `feat: #<N> (<actor>) — <imperative summary>`, PR body carrying
`Closes #<N>`, exactly two labels per issue (route + lead), reviewer verdicts as evidence on the pull
request only, one issue in flight at a time, and the author never the reviewer. Router → executor →
independent reviewer → factory merge; three changes requested on the same pull request stop the chain
and record that a human is needed.

The trail is on the tracker and in the history. Issue numbers as carried by the commit subjects, PR
numbers as carried by the merge commits present in this clone's history:

| Issue | PR | What it produced |
|---|---|---|
| #1 | #31 | README and AGENTS.md, the pack as the authoritative layer, the index of the modular docs |
| #2 | #32 | docs/agent-team-spec.md: roles, process, verdicts, the rubric numbers as corrected |
| #3 | #33 | docs/tracker.md: one issue = one PR, branch, commit subject, labels, evidence-only verdicts |
| #4 | #34 | The test seam, the three fixtures, the readable-failure mechanism |
| #5 | #35 | Seed configuration and the domain model, read back over HTTP |
| #6 | #36 | The machine state machine and the rejection of invalid hops |
| #7 | #37 | Valid start times for real cycle durations (R1, R2) |
| #8 | #38 | Public availability per type with refusal reasons |
| #9 | #39 | Email + in-app OTP sign-in, and the telemetry guard that refuses credentials |
| #12 | #57 | The narrow still-occupied claim (R10) read at the report surface |
| #13 | #58 | Device reports, the in-process simulator, the `idle_open` event |
| #15 | #56 | The cancellation window (R4) |
| #16 | #64 | The constrained fault report and maintenance (R7) |
| #17 | #65 | Reassignment with new code and notification (R8) |
| #18 | #60 | The no-show counter and the booking block (R9) |
| #19 | #66 | The per-customer daily limit (R11) |
| #48 | #55 | The loser's 409 shaped as the bounded set the customer can take, slice c of #11 |
| #61 | #63 | A supplied test restored byte-exact from the fence, with the decision recorded on the issue |

Two parts of the evidence are conventions the harness enforces rather than documents it writes: the
sha256 tamper-check of every test supplied in an issue, and the rule that a supplied file runs exactly
as given (which is why the contradictions above are recorded in `tests/fixtures.py` instead of resolved
by editing a test). Booking creation (issue #11) is the work split into slices the tracker shows as #45
and #48, so its trail carries a slice number rather than one issue number.

## Authoritative spec layer

| File | Role |
|---|---|
| [docs/spec.md](docs/spec.md) | Project specification: problem, solution, user stories, rules R1-R11, testing decisions, out of scope |
| [docs/addendum-firma.md](docs/addendum-firma.md) | Signed correction layer — wins on every conflict with `docs/spec.md` |

Those two files are the whole authoritative spec layer. The outcome recorded by the harness trial is in
[docs/ESITO.md](docs/ESITO.md); the process and the roles in
[docs/agent-team-spec.md](docs/agent-team-spec.md); the tracker conventions in
[docs/tracker.md](docs/tracker.md).

## Project context

- [AGENTS.md](AGENTS.md) — entry point for the agent team, indexes the modular docs under `docs/`. It is
  not a specification.
- Interface language: Italian. Documentation language: English.
- Paths are repository-relative. No host path, no secret, no token, no key in any file, and no internal
  tailnet hostname anywhere in the documentation.
