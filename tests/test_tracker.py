"""Checks on docs/tracker.md — the tracker conventions for one-issue-in-flight.

The document is the convention that produces the "agents used the tracker" evidence: one issue =
one PR, the branch, the commit subject, the two labels, the title override the router honours, and
the verdict labels as evidence-only. The worked example references a real issue number. It is
documentation, so it is in English and it carries no host path and no credential.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACKER = ROOT / "docs" / "tracker.md"
AGENTS = ROOT / "AGENTS.md"
TEAM_SPEC = ROOT / "docs" / "agent-team-spec.md"

POSIX_ABSOLUTE = re.compile(r"(?<![\w.'])/(?:[\w.-]+/)+")
WINDOWS_ABSOLUTE = re.compile(r"[A-Za-z]:\\\\[\w.-]")
SECRET_MARKERS = ("gho_", "ghp_", "sk-", "token=", "secret=", "key=", "-----BEGIN")
ITALIAN_MARKERS = ("è", "é", "ò", "à", "ì", "ù", "perché", "nell'", "dell'", "dalla",
                   "delle", "cartella", "viaggia", "documento di progetto")

ROUTE_LABELS = ("`atomic`", "`complex`")
VERDICT_LABELS = ("`review:approved`", "`review:changes-requested`", "`review:needs-human`")


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(path: pathlib.Path) -> str:
    """Prose on one line: markdown wraps, the facts must survive the wrapping."""
    return " ".join(read(path).split())


def test_ac1_the_unit_of_work_conventions():
    text = flat(TRACKER)
    assert "**one issue = one PR**" in text
    assert "`feat/issue-<N>`" in text
    assert "`feat: #<N> (<actor>) — <imperative summary>`" in text
    assert "`Closes #<N>`" in text


def test_ac2_exactly_two_labels_route_plus_lead():
    text = flat(TRACKER).lower()
    assert "exactly two labels" in text
    for label in ROUTE_LABELS:
        assert label in text, label
    assert "`lead:<name>`" in flat(TRACKER)
    assert "cli that split the backlog" in text


def test_ac3_the_title_prefix_is_the_override_the_router_honours():
    text = flat(TRACKER)
    assert "`[atomic]` / `[complex]`" in text
    assert "manual override the router honours" in text
    assert "the lead's sizing survives routing" in text


def test_ac4_verdict_labels_are_evidence_only_not_issue_labels():
    text = flat(TRACKER)
    for label in VERDICT_LABELS:
        assert label in text, label
    assert "evidence-only" in text
    assert "not as issue labels" in text
    assert "stops the chain" in text  # anti-loop guard, recorded as evidence on the PR


def test_ac5_the_worked_example_references_a_real_issue_number():
    text = flat(TRACKER)
    assert "Worked example" in text
    assert "Issue **#1**" in text
    assert "pull request **#31**" in text
    assert "feat: #1 (qwen-code) — add the project context files README and AGENTS.md" in text
    assert "Closes #1." in text
    # the referenced files are real repository files, not a placeholder
    assert (ROOT / "README.md").is_file()
    assert (ROOT / "tests" / "test_context_files.py").is_file()


def test_ac6_no_host_paths_no_secrets_no_token_names_and_english():
    text = read(TRACKER)
    assert not POSIX_ABSOLUTE.search(text)
    assert not WINDOWS_ABSOLUTE.search(text)
    assert not [m for m in SECRET_MARKERS if m in text], [m for m in SECRET_MARKERS if m in text]
    # no credential name either: a token name would be an uppercase constant or a scope name
    assert not re.search(r"[A-Z]{2,}_TOKEN|[A-Z]{2,}_PAT", text)
    assert not [m for m in ITALIAN_MARKERS if m in text.lower()], text


def test_the_tracker_conventions_do_not_contradict_the_process_and_the_index():
    spec = flat(TEAM_SPEC).lower()
    tracker = flat(TRACKER).lower()
    assert "one issue in flight at a time" in tracker
    assert "one issue = one pr" in tracker
    assert "one pull request per issue" in spec
    assert "feat/issue-<n>" in spec.lower()
    assert "`docs/tracker.md`" in read(AGENTS)
    assert "docs/tracker.md" in flat(AGENTS)
