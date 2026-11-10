"""Checks on docs/agent-team-spec.md — the agent team specification.

The document names every role and what it owns, states the process, records the rubric numbers as
corrected by the addendum patch 4, and records the mixed model. It is documentation, so it is in
English and it carries no host path and no credential.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "agent-team-spec.md"
AGENTS = ROOT / "AGENTS.md"

POSIX_ABSOLUTE = re.compile(r"(?<![\w.'])/(?:[\w.-]+/)+")
WINDOWS_ABSOLUTE = re.compile(r"[A-Za-z]:\\\\[\w.-]")
SECRET_MARKERS = ("gho_", "ghp_", "sk-", "token=", "secret=", "key=", "-----BEGIN")
ITALIAN_MARKERS = ("è", "é", "ò", "à", "ì", "ù", "perché", "nell'", "dell'", "dalla",
                   "delle", "cartella", "viaggia", "documento di progetto")

ROLES = {
    "lead": ("issue splitting", "sizing", "ordering"),
    "executor": ("one issue in flight", "src/", "tests/"),
    "reviewer": ("docs/spec.md", "docs/addendum-firma.md", "pull request"),
    "router": ("atomic", "complex", "label"),
}


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(path: pathlib.Path) -> str:
    """Prose on one line: markdown wraps, the facts must survive the wrapping."""
    return " ".join(read(path).split())


def test_the_spec_names_every_role_and_what_it_owns():
    text = flat(SPEC)
    for role, owns in ROLES.items():
        assert f"**{role}**" in text, role
        for fact in owns:
            assert fact in text, f"{role}: {fact}"


def test_the_spec_states_the_process_and_the_verdicts():
    text = flat(SPEC).lower()
    assert "one issue in flight at a time" in text
    assert "one pull request per issue" in text
    assert "author is never the reviewer" in text
    for verdict in ("go", "go-con-note", "risubmit"):
        assert f"**{verdict}**" in text, verdict


def test_the_spec_records_the_rubric_numbers_as_corrected_by_patch_4():
    text = flat(SPEC)
    for fact in ("12 criteria", "24 points", "pass 10",
                 "5/24", "2 + 1 + 2", "19/24", "16", "14"):
        assert fact in text, fact
    assert "3 as `docs/spec.md` states" in text


def test_the_spec_records_the_mixed_model():
    text = flat(SPEC).lower()
    assert "frontier model" in text
    assert "cloud endpoint" in text
    assert "local inference" in text
    assert "whole chain" in text


def test_the_on_call_responder_is_domain_level_only():
    text = flat(SPEC)
    assert "domain level" in text
    assert "`maintenance`" in text
    assert "R8 reassignment" in text
    assert "escalates to the owner" in text
    assert "never code-changing and never PR-opening" in text


def test_agents_md_links_the_agent_team_specification():
    assert "docs/agent-team-spec.md" in read(AGENTS)


def test_the_spec_has_no_host_paths_no_secrets_and_is_in_english():
    text = read(SPEC)
    assert not POSIX_ABSOLUTE.search(text)
    assert not WINDOWS_ABSOLUTE.search(text)
    assert not [m for m in SECRET_MARKERS if m in text]
    assert not [m for m in ITALIAN_MARKERS if m in text.lower()], text
