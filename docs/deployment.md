# Deployment

The deployment steps, in English, exactly as the criterion is earned here.

**Deployment and continuous deployment are out of scope** (addendum patch 3): there is **no public URL**
and **no continuous deployment**. The project does not claim the points a public deployment would earn. The
in-scope compensation is this document — **tier 1 of the Deployment criterion, 1 point** — plus the CI
tier-1 gate on every pull request, 1 point (issue #29, conventions in [tracker.md](tracker.md)).

Every step below runs on the machine the checkout is on. The steps a public host would need are written as
steps and marked **not executed**: writing deploy steps the system does not perform would misrepresent what
the system does.

Project context entry point: [AGENTS.md](../AGENTS.md). Authoritative spec layer: [spec.md](spec.md) +
[addendum-firma.md](addendum-firma.md) — the addendum wins on every conflict. Process and roles:
[agent-team-spec.md](agent-team-spec.md). Tracker conventions: [tracker.md](tracker.md). The whole picture
is in [README.md](../README.md).

## The numbers this document uses (patch 4)

**12 criteria, 24 points, pass 10.** The observability + alert + on-call chain is **5/24** (2 + 1 + 2), not
3 as `docs/spec.md` states. With deployment out of scope: **realistic ceiling 19/24**, base **16** without
the chain, user target **14**, pass **10**. The 1 point of the documented deployment steps and the 1 point
of CI tier 1 sit inside that ceiling; the chain's 5 are not earned today, because only its instrumentation
half exists.

## Prerequisites

| Tool | Why | Check |
|---|---|---|
| Docker with Compose v2 | the one-command start, the lab topology | `docker compose version` |
| Python 3.11 or newer | the backend process and the test suite | `python3 --version` |
| git | the checkout and the branch convention of `docs/tracker.md` | `git --version` |
| pytest | the single test command | `python3 -m pytest --version` |
| curl | the health check and the failure demo | `curl --version` |

Optional, and only for the PostgreSQL path: `psycopg`. Without a reachable server `src/db.py` cannot use
PostgreSQL and the process refuses to start rather than pretending, because the SQLite fallback needs a
file path and the process gives it none. `httpx` is optional too: `tests/seam.py` falls back to the stdlib,
so a clean checkout needs pytest and nothing else.

## Running it from a clean checkout

```bash
git clone <repo> && cd quick-wash
docker compose up            # .devcontainer/docker-compose.yml
```

What that starts is stated as a fact: the two services the repository declares — `gate` (the squid allowlist
proxy) and `app` (the container the work happens in). The compose file declares no database service and no
service that starts the application, so `docker compose up` is the lab, not the running system. The lab
network is internal: no published port, and no route out except through the gate.

Inside the container, the command that exercises the whole system today is the single test command:

```bash
python3 -m pytest -q
```

It starts the real HTTP server on 127.0.0.1 and the repository on a real relational database: nothing is
mocked, nothing leaves the machine. To run the application as a process instead, a database has to be
reachable:

```bash
export QW_DATABASE_URL="postgresql://<db-user>:<db-password>@<db-host>:5432/<db-name>"
python3 -m src.server        # binds 127.0.0.1, PORT defaults to 8000
```

There is no build step, no install step and no migration step beyond the tables the repository layer
creates on start. Seeding is part of the start, not a command of its own.

## Seeding

`Application.__init__` calls `Repository.reset()`, which recreates the tables and writes the seed on every
start. On a clean checkout that is the pack's inventory, eight machines:

| Type | Machines | kg | Cycle | Tokens |
|---|---|---|---|---|
| `standard` | M1-M4 | 6 | 60 minutes | 4 |
| `family` | M5-M6 | 8 | 75 minutes | 6 |
| `quick` | M7-M8 | — | 30 minutes | 3 |

The rest of the seed is configuration held as data and read back over HTTP at `GET api/availability`:
opening 07:00-22:00, closed on Sundays, 15-minute grid, 10-minute grace, 15-minute cancellation window,
turnover buffer 10 minutes and cleaning buffer 30 minutes (addendum patch 2), 15-minute `idle_open` bound,
2 no-shows in 30 days blocking new bookings for 7 days, 2 bookings per customer per shop day
(`Europe/Rome`), a 10-minute single-use one-time code, and the owner identity as the configured
`owner_email`. Nothing is editable through a screen: the only write the seam accepts on the inventory is
`POST api/machines` with a `type`, which adds one machine of that type (demo mode). Tariff and duration stay
the type's, never a machine row's.

## Ports

| Port | What is on it | Where it comes from |
|---|---|---|
| 8000 | the backend, bound to 127.0.0.1 | `PORT`, default 8000 |
| 5432 | PostgreSQL | the host part of `QW_DATABASE_URL` |
| 3128 | the lab egress gate (squid), not the application | the compose service `gate` |

Nothing is published. The backend binds to 127.0.0.1 and the lab network is internal, so the application is
reachable only from the machine it runs on: **there is no public URL**, and no step in this document
contradicts patch 3.

## Environment variables

The application reads exactly two variables. Every value below is a placeholder — no real host, no real
user, no password, no token, no key. Nothing is committed here: `.env` and `.env.*` are gitignored, and no
file in the repository carries a credential.

| Variable | Default (placeholder) | Read by |
|---|---|---|
| `QW_DATABASE_URL` | `postgresql://<db-user>:<db-password>@<db-host>:5432/<db-name>` | `src/db.py`, through `default_url()`; the built-in default names the local pair for the compose service, and when no server is reachable the adapter falls back to a file-backed SQLite database only if a path is given |
| `PORT` | `8000` | `src/server.py` |

Those two are the whole surface. A deployment that needs a third variable is a deployment this system does
not have.

## The observability UI, stated as what exists

The rubric asks for correlated metrics, traces and structured logs viewable in a UI, with no customer data
in telemetry. What the repository has is the read, not a dashboard:

```bash
curl -s localhost:8000/api/logs/recent
```

It answers with `{"entries": [...], "metrics": {"customer_blocked_total": 0}}`: one structured line per
request of the instrumented journey (booking → redeem → cycle start → cycle finish), one metric of
customer-blocked events, and a trace identifier shared by every line and every metric attached to that
journey. The trace is hashed from the internal booking id, so it names the journey without naming a
customer or a code, and the guard in `src/telemetry.py` refuses rather than redacts: a line that would
carry a customer email, an unlock code, a one-time code or any credential is never stored and never
printed. `tests/unit/test_telemetry_guard.py` asserts that.

There is no dashboard page, and the alert and the on-call responder that would complete the 5/24 chain do
not exist: the chain is worth 5/24 (2 + 1 + 2) and only its instrumentation half is built.

## Health check

There is no dedicated health route. The probe that proves the two things a deployment can fail on — the
process answering, and the database being reachable — is the seed read, because the seed is read from the
database and not from the code:

```bash
curl -s localhost:8000/api/availability      # 200: opening hours, closed days, the seed read back
```

A 200 there means the process is up, the repository layer reached the database, and the numbers the tests
read are the numbers the seam answers with. `curl -s localhost:8000/api/logs/recent` proves the recorder.
Both reads answer without a session, so a probe needs no identity. No compose `healthcheck` is declared
today, because no application service is declared.

## Reproducing the failure demo after deployment (issue #24)

The fault is deterministic — open decision 1, accepted as signed: the trigger is a request on one of the
surfaces that write `maintenance`, and `Application.apply_fault` is the only writer of that hop, so the
demo, the test and the reviewer see one implementation. The header below is the session token the sign-in
produced: `POST api/session` shows the one-time code in-app (patch 1) and `POST api/session/verify` redeems
it, so there is no email and no SMS to wait for.

Three commands:

```bash
# 1 - the turn that makes the report entitled under R7; the answer names the machine, M5 on the seed
curl -s -X POST localhost:8000/api/bookings -H "Authorization: Bearer <session-token>" -H 'Content-Type: application/json' -d '{"type":"family","start":"13:00"}'

# 2 - the deterministic trigger: the report of the customer who has the booking moves the machine out of service
curl -s -X POST localhost:8000/api/lock/reports -H "Authorization: Bearer <session-token>" -H 'Content-Type: application/json' -d '{"event":"fault","machine":"M5"}'

# 3 - the outcome, as an externally observable fact
curl -s localhost:8000/api/incidents
```

The start time is the first example the shop can still take: the grid quantises it and a slot that has
already begun is refused, so run the demo on a start ahead of the moment the request arrives.

What the three commands show: 201 with the machine, the start, the expected end and the tokens; 200 with
`outcome` `maintenance`, the incident `fault`, and the R8 pass moving the turn to the lowest-numbered free
machine of the type (`M6`) with a new code, earliest start first, ties broken by creation order; then the
incident list carrying `fault` and `reassignment`. The booking line, the report line and the incident share
one trace identifier, so the telemetry read shows the journey as one trace.

What does not happen is the alert: nothing alerts and nobody is paged, so the demo earns the
instrumentation half of the chain only.

## Tests and CI (issue #29)

The single test command is `pytest`, run as `python3 -m pytest -q`; `pytest.ini` sets `testpaths = tests`
and `pythonpath = .`. Unit tests stay on the three pure pieces — valid start times, the grace window, the
no-show counter and its block expiry — and the integration tests drive the whole journey through the HTTP
seam against a real database.

CI is tier 1, and it is where it says: `.github/workflows/pi-review.yml`, on the self-hosted factory runner
(factory-1), runs `python3 -m pytest -q` on every pull request, plus the sha256 tamper-check of the test
files supplied in an issue (`.github/scripts/verify_tests.py`). That gate is the whole of CI: no Actions
minutes consumed, and **no deploy step** — no workflow in `.github/workflows/` deploys anything, and the
other three workflows are the tracker loop (route, implement, review, merge), not a delivery pipeline.

## The public-host steps: written, not executed

Out of scope by patch 3. Recorded so the reader can see what the criterion would ask for, and claimed as
nothing: these steps are **not executed**, none of them earns a point, and the 19/24 ceiling of patch 4
already assumes they are absent.

1. Declare the application as a compose service with PostgreSQL as a second service, a published port and a
   database volume. The repository declares neither.
2. Create the tables against the deployed database instead of at process start.
3. Put the process behind a reverse proxy with TLS and a service-level health check.
4. Add a deploy step to CI — the tier-2 and tier-3 half of the CI/CD criterion, which the project trades
   away for the budget.
