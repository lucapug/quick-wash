# quick-wash

Token-based washing machine booking for one unattended laundromat: eight machines, no
staff on site. quick-wash reserves a cycle, not a time window — it assigns a specific
machine and an explicit start time, issues a numeric unlock code the customer types on
the machine keypad, and records what really happened at the machine (no-shows, faults,
cleaning). The application never handles money: payment is physical, in tokens, at the
machine.

## Start

```bash
docker compose up
```

One command starts the whole system, database included.

## Test

```bash
pytest
```

The single test command runs both unit tests and integration tests. The integration tests
drive the whole journey through one seam: the HTTP boundary of the backend.

## Authoritative spec layer

| File | Role |
|---|---|
| [docs/spec.md](docs/spec.md) | Project specification: problem, solution, user stories, rules R1-R11, testing decisions, out of scope |
| [docs/addendum-firma.md](docs/addendum-firma.md) | Signed correction layer — wins on every conflict with `docs/spec.md` |

Those two files are the whole authoritative spec layer.

## Project context

- [AGENTS.md](AGENTS.md) — entry point for the agent team, indexes the modular docs under `docs/`. It is not a specification.
- Interface language: Italian. Documentation language: English.
- Paths are repository-relative. No host path, no secret, no token, no key in any file.
