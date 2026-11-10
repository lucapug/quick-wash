# Tracker Conventions

The tracker is the public issue list of this repository. The evidence that the agents used the
tracker is produced by convention, not by a tool: every issue number is carried by the branch,
the commit subject and the pull request body, so the trail is visible on the tracker itself and
never has to be reconstructed afterwards.

Project context entry point: [AGENTS.md](../AGENTS.md). Process and roles:
[agent-team-spec.md](agent-team-spec.md). Backlog source of truth: [ESITO.md](ESITO.md).

All paths in this document are repository-relative. No host path, no secret, no token name.

## The unit of work

| Convention | Rule |
|---|---|
| Issue | **one issue = one PR** — no PR carries work from two issues, no issue is closed by two PRs |
| Branch | `feat/issue-<N>` where `<N>` is the issue number |
| Commit subject | `feat: #<N> (<actor>) — <imperative summary>` |
| PR body | links the issue number with `Closes #<N>`, so the merge closes the issue and the issue page shows the PR back-reference |

`<actor>` is the agent that produced the commit (the executor of the issue), for example
`qwen-code` or `pi-actor`. The summary is an imperative summary of the work in one line: the
issue title in imperative form, never a run marker — a retry counter is recorded in the PR
comment, not in the commit subject.

The one-issue-in-flight rule — **one issue in flight at a time**, no issue started while another
one is still open in the chain — is what makes the branch name, the commit subject and the PR body
unambiguous: there is exactly one number in the trail, and it is the issue number.

## Labels: exactly two per issue

Every issue carries exactly two labels.

1. The route label: **`atomic`** or **`complex`**, applied by the router when the issue is opened.
2. The lead label: **`lead:<name>`** — the CLI that split the backlog. For the backlog transferred
   into this repository the lead label is `lead:qwen-code` (verdict recorded in
   [ESITO.md](ESITO.md)); a different CLI in charge of the split writes its own name.

No other label belongs on an issue.

### The title prefix is the manual override

The `[atomic]` / `[complex]` prefix in the issue title is the manual override the router honours.
When the prefix is present the router applies that label without re-sizing the issue, so the
lead's sizing survives routing: the prefix is the lead's decision, the router only records it.
Without a prefix the router decides, and low confidence or an invalid answer falls back to
`complex`, as stated in [agent-team-spec.md](agent-team-spec.md).

So the title keeps the lead's sizing legible on the tracker, and the label keeps the route
machine-readable: `atomic` is a surgical change on an existing repository, `complex` needs
planning, several steps or a decision.

## Verdict labels are evidence-only

The reviewer verdict labels — `review:approved`, `review:changes-requested`,
`review:needs-human` — are recorded as evidence on the pull request (review comment, commit
status, label on the PR), **not as issue labels**: an issue keeps only its two labels above.
The verdict is a fact about a pull request, not a state of the issue; a verdict label on an
issue would break the two-label rule and mix the routing state with the review state.

The anti-loop guard — three `review:changes-requested` on the same pull request — stops the chain
and records that a human is needed; that record is evidence on the pull request, still not an extra
issue label. Where a CI writer puts a verdict marker on the issue instead, it contradicts this
convention and is corrected, not re-documented here.

## Worked example

Issue **#1** — `[atomic] Establish the project context files README and AGENTS.md`, labels
`atomic` + `lead:qwen-code`, closed by pull request **#31** on branch `feat/issue-1`.

Commit subject:

```text
feat: #1 (qwen-code) — add the project context files README and AGENTS.md
```

PR **#31** body:

```text
Closes #1.

Implements the acceptance criteria of issue #1: README.md and AGENTS.md as the project
context files, the pack as the authoritative spec layer, and the index of the modular docs.
Tests: tests/test_context_files.py, byte-identical to the test supplied in the issue.
```

The trail is `issue #1 -> PR #31 -> merge commit -> issue #1 closed`: every link carries the
issue number, so the tracker shows the agent work without any reconstruction. The same shape
applies to every issue — for example this document, issue #3, branch `feat/issue-3`.
