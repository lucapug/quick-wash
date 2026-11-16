# AGENTS.md — quick-wash project context

Project context entry point for the agent team. Everything in this repository is documented
in English; the product interface (UI copy and user-facing strings) is in Italian.

## Authoritative spec layer

The authoritative spec layer is exactly two files:

- `docs/spec.md` — the project specification.
- `docs/addendum-firma.md` — the signed audit addendum, the correction layer.

**The addendum wins on every conflict with `docs/spec.md`.** Where the two disagree, the
addendum is what agents implement and what a reviewer grades against. Concretely the
addendum overrides `docs/spec.md` on:

1. **Buffers (R10)** — turnover **10 minutes**, cleaning **30 minutes**, held in
   seed/configuration as tariffs and hours.
2. **Deployment and CD are out of scope** — no public URL, no continuous deployment. The
   in-scope compensation is the deployment steps written in the documentation and CI
   tier 1 on every pull request.
3. **The observability + alert + on-call chain is worth 5/24** (2 + 1 + 2), not 3 as
   `docs/spec.md` states. With deployment out of scope: realistic ceiling **19/24**, base
   **16** without the chain, target **14**, pass **10**.
4. **OTP is displayed in-app** immediately after the sign-in request (demo mode): no email
   or SMS transport, and it may never appear in telemetry.
5. **Open decisions 1-3 are accepted as signed** — deterministic fault trigger, alert on
   customer impact, domain-level on-call responder. Everything runs locally in compose.

## Modular docs index

- `docs/spec.md` — specification: problem, solution, user stories, machine state machine, rules R1-R11, testing seam, out of scope, open decisions.
- `docs/addendum-firma.md` — signed addendum: the correction layer that wins on every conflict, and the operating notes for the agent team.
- `docs/ESITO.md` — recorded outcome of the harness trial and the transfer map from the winning backlog to this repository's issues.
- `docs/agent-team-spec.md` — agent team specification: roles and what each owns, the one-issue-in-flight process, the review protocol (GO / GO-con-note / RISUBMIT), the rubric numbers as corrected by the addendum, and the mixed model.
- `docs/tracker.md` — tracker conventions: one issue = one PR, the branch, the commit subject, the two labels per issue, the title override the router honours, and the evidence-only verdict labels.
- `docs/deployment.md` — the deployment steps, tier 1 of the Deployment criterion: prerequisites, the run from a clean checkout, seeding, ports, the observability read, the health check, the environment variables as placeholders, the three commands of the failure demo, and where the CI gate runs. No public URL and no continuous deployment.

This index lists every file under `docs/`, one line per file.

## Working conventions

- This file lives at the repository root as the context entry point: it is not one of the
  modular docs indexed above.
- One issue in flight at a time; the author is never the reviewer.
- Implementation lives in `src/`, tests live in `tests/`; the single test command is
  `pytest` and the single start command is `docker compose up`.
- Paths in issues, tests and documentation are repository-relative (`docs/spec.md`,
  `tests/test_booking.py`) — never host paths.
- No secret, token, key or credential in any file, and no customer email, unlock code or
  one-time code in telemetry.
- Language split: Italian for the interface, English for all documentation.
