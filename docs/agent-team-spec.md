# Agent Team Specification

The team that builds quick-wash: who owns what, in what order, and against which document.
Project context entry point: [AGENTS.md](../AGENTS.md). Authoritative spec layer:
[spec.md](spec.md) + [addendum-firma.md](addendum-firma.md) — the addendum wins on every conflict.

All paths in this document are repository-relative. No host path, no secret, no token, no key.

## Roles

| Role | Owns |
|---|---|
| **lead** | issue splitting, sizing, ordering |
| **executor** | one issue in flight, implementation in `src/` and tests in `tests/` |
| **reviewer** | evaluates pull requests against `docs/spec.md` + `docs/addendum-firma.md` |
| **router** | applies the `atomic` / `complex` label when an issue is opened |

### lead

Owns the shape of the work: it splits the specification into issues, sizes each one so it can be
closed inside the budget, and orders them. The tracker half of the Product Specification criterion
is the lead's output — tasks carry acceptance criteria, and rules R1-R11 of `docs/spec.md` are
lifted into tracker tasks directly. The lead does not write code and does not review.

### executor

Owns exactly one issue at a time. It implements the issue as a single pull request, keeps
implementation in `src/` and tests in `tests/`, and never touches files outside that scope. A test
file supplied in the issue arrives in the pull request byte-identical: the executor may not adjust a
test to make it pass. The executor is never the reviewer of its own work.

### reviewer

Owns the verdict. It evaluates a pull request against `docs/spec.md` + `docs/addendum-firma.md` —
in particular the patches that change numbers and behaviour (buffers 10/30, deployment out of
scope, the corrected arithmetic, the domain-level responder), which are graded against the addendum
even when `docs/spec.md` says otherwise. It checks the acceptance criteria as written in the issue:
correctness, tests present and unmodified, nothing outside scope touched. It runs the test command
itself rather than trusting the report, and it does not edit any file.

### router

Owns the route. When an issue is opened it applies the `atomic` / `complex` label: `atomic` is a
surgical change on an existing repository (few files, clear criteria, no architectural decision),
`complex` is anything that needs planning, several steps, or a decision. A manual `[atomic]` /
`[complex]` prefix in the title overrides the router; low confidence or an invalid answer falls back
to `complex`, because a wrong route costs the team process while a complex task routed as atomic
risks producing a mess.

## Process

1. The lead splits, sizes and orders the issues; the router labels each issue as it is opened.
2. **One issue in flight at a time.** No issue is started while another one is still open in the
   chain.
3. **One pull request per issue**, branch `feat/issue-<n>`, commits and the pull request reference
   the issue number — that reference is the evidence that the agents used the tracker.
4. **The author is never the reviewer.** The reviewer is an independent agent that reads the issue
   and the diff, runs the tests, and issues a verdict.
5. Verdicts:
   - **GO** — every acceptance criterion is met as written. Merge.
   - **GO-con-note** — accepted, with a note that must be carried forward (a follow-up issue, a
     documentation correction, a known limitation). Merge, and the note lands in the record.
   - **RISUBMIT** — a criterion is not met. The request is sent back to the author with the
     specific change required, and the issue is re-queued; the reviewer does not fix the code.
6. The audit of the whole trial is the reviewer of record for the rubric grade and is the source of
   the signed correction layer.

## Rubric numbers (patch 4 of the addendum)

The documentation uses these numbers, not the ones in `docs/spec.md`:

- **12 criteria, 24 points, pass 10** — DataTalksClub AI Dev Tools Zoomcamp 2026.
- The **instrumentation + alert + on-call chain is 5/24** (2 + 1 + 2), not 3 as
  `docs/spec.md` states. The three links fail together: a weak link zeroes all three.
- **Realistic ceiling with deployment out of scope: 19/24.** Deployment and CD are out of scope; the
  in-scope compensation is the deployment steps written in the documentation (tier 1, 1 point) plus
  CI tier 1 on every pull request (1 point).
- **Base without the chain: 16.** The chain checkpoint is 13/11: if the alert + on-call chain cannot
  be demonstrated, the project freezes at base 16.
- **User target: 14.**

## Model allocation (the mixed model)

The team runs on a mixed model:

- **Audit on a frontier model**, through a cloud endpoint (the auditor that produced the signed
  addendum, and the reviewer of record for the rubric grade).
- **Local inference for the whole chain** — the local machine carries every stage of the factory:
  brainstorm and specification (architect IQ3_XXS), lead in probation (qwen-code vs opencode),
  executor, reviewer (Z1 on the local RTX 3070), and the router.

The reason is budget: frontier calls are spent only where a judgement is worth more than the tokens,
and everything that runs many times a day runs locally. The consequence for the team is that the
pack is materialised inside the project folder in the container — `docs/spec.md` and
`docs/addendum-firma.md` — because agents isolated in the container cannot read anything outside the
repository, and issues never reference a host path.

## Decision: the on-call responder is domain-level only

The on-call responder acts at the domain level: it puts the failing machine into `maintenance`,
triggers the R8 reassignment for the affected bookings, records the incident, and stops and
escalates to the owner when no machine of the type is free.

It is **never code-changing and never PR-opening**. This records the accepted recommendation of the
architect (open decision 3, signed): acting at infrastructure level may be added, but writing code
and opening a pull request is the most spectacular option and the most fragile one at this budget —
and it would be judged on the same 5/24 chain that a weak link zeroes.

Related accepted decisions that shape the same chain: faults are deterministic (a configuration
switch or an owner-panel action, US61), and the alert fires on customer impact, not on system load.
Everything runs locally in compose — no cloud resource.
