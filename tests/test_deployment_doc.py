"""Checks on docs/deployment.md — the deployment steps, the tier-1 half of the Deployment criterion.

Deployment and CD are out of scope (addendum patch 3): no public URL, no continuous deployment. The point
this criterion can pay is the documented steps at tier 1, so the document is graded as written: the steps
must be the ones the repository can actually run, the env values must be placeholders, the failure demo
must be reproducible in three commands, the test command and the CI location must be named, the rubric
numbers must be patch 4's, and the doc must be reachable from README.md and from AGENTS.md.

The document is in English, carries no host path and no credential — the same hygiene the other modular
docs are checked with.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "deployment.md"
README = ROOT / "README.md"
AGENTS = ROOT / "AGENTS.md"

POSIX_ABSOLUTE = re.compile(r"(?<![\w.'])/(?:[\w.-]+/)+")
WINDOWS_ABSOLUTE = re.compile(r"[A-Za-z]:\\\\[\w.-]")
SECRET_MARKERS = ("gho_", "ghp_", "sk-", "token=", "key=", "-----BEGIN")
ITALIAN_MARKERS = ("è", "é", "ò", "à", "ì", "ù", "perché", "nell'", "dell'", "dalla",
                   "delle", "cartella", "viaggia", "documento di progetto")

# Patch 4 of the addendum: the numbers the documentation uses.
RUBRIC = ("12 criteria", "24 points", "pass 10", "5/24", "2 + 1 + 2", "19/24", "16", "14")

# The pieces a deployment document has to cover (AC1).
COVERED = ("docker compose up", "seeding", "port", "observability", "health check", "prerequisite")


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def flat(text: str) -> str:
    """Prose on one line: markdown wraps, the facts must survive the wrapping."""
    return " ".join(text.split())


def section(text: str, heading: str) -> str:
    """One section of a markdown file: from a heading to the next heading."""
    start = text.index(heading)
    rest = text[start + len(heading):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def env_names(text: str) -> set:
    """The variables the application reads, taken from the source rather than from the doc."""
    found = set()
    for path in (ROOT / "src").glob("*.py"):
        found |= set(re.findall(r"environ(?:\.get)?\(\"([A-Z][A-Z_]+)\"", path.read_text(encoding="utf-8")))
    return found


def seam_paths() -> set:
    """The paths the seam answers on, read from src/app.py."""
    from src import app

    entries = {path for _, path in app.ROUTES}
    entries |= {path.split(" ")[1] for path in app.PATTERNS}
    entries |= {path.split(" ")[1] for path in app.SEED_WRITE}
    for pattern in (app.CUSTOMER_VIEW, app.PER_MACHINE_READ, app.BOOKING_SURFACE, app.BOOKING_CANCEL,
                    app.REPORT_SURFACE):
        entries.add(pattern[1])
    entries.add(app.OWNER_PANEL)
    return {entry.strip("/") for entry in entries}


def test_ac1_the_document_exists_and_covers_the_run_from_a_clean_checkout():
    text = flat(read(DOC))
    for fact in COVERED:
        assert fact in text.lower(), fact
    # The steps are the ones this repository can actually run: the test command starts the whole system,
    # and the process path needs a database.
    assert "python3 -m pytest -q" in text
    assert "python3 -m src.server" in text
    assert "seeding is part of the start, not a command of its own" in text.lower()


def test_ac2_no_public_url_and_no_cd_and_the_point_is_tier_1():
    text = flat(read(DOC))
    assert "**no public URL**" in text
    assert "**no continuous deployment**" in text
    assert "out of scope" in text
    assert "tier 1 of the Deployment criterion, 1 point" in text
    # The public-host steps are written as steps and flagged as not executed, never as work done.
    not_executed = flat(section(read(DOC), "## The public-host steps: written, not executed"))
    # The phrase has to survive the wrapping, not sit only in the heading: the section says the steps are
    # not executed, and claims nothing for them.
    assert "not executed" in not_executed
    assert "none of them earns a point" in not_executed
    assert "19/24" in not_executed  # the ceiling already assumes they are absent


def test_ac3_the_environment_variables_are_the_two_the_code_reads_and_are_placeholders():
    block = section(read(DOC), "## Environment variables")
    named = set(re.findall(r"`([A-Z][A-Z_]+)`", block))
    assert named == env_names(read(DOC)), named
    for name in ("QW_DATABASE_URL", "PORT"):
        assert name in named, name
    # Every value is a placeholder: no host, no user, no password, no token, no key.
    for placeholder in ("<db-user>", "<db-password>", "<db-host>", "<db-name>"):
        assert placeholder in block, placeholder
    assert "placeholder" in block
    assert not [m for m in SECRET_MARKERS if m in block], [m for m in SECRET_MARKERS if m in block]


def test_ac4_the_failure_demo_is_three_commands_on_surfaces_the_seam_answers_on():
    block = section(read(DOC), "## Reproducing the failure demo after deployment (issue #24)")
    commands = [line for line in block.splitlines() if line.startswith("curl")]
    assert len(commands) == 3, commands
    # The deterministic trigger is a request on a seam path, not a fourth core: R7, then the R8 pass.
    for path in ("api/bookings", "api/lock/reports", "api/incidents"):
        assert path in block, path
    assert "deterministic" in flat(block)
    assert "`maintenance`" in block
    assert "fault" in flat(block) and "reassignment" in flat(block)
    # And the honest half: the alert does not fire, so the chain is not earned by this demo.
    assert "nothing alerts" in flat(block)


def test_ac5_the_single_test_command_and_where_ci_runs():
    text = flat(read(DOC))
    assert "single test command" in text
    assert "`pytest`" in text
    assert "python3 -m pytest -q" in text
    workflow = ".github/workflows/pi-review.yml"
    assert workflow in text
    assert (ROOT / workflow).is_file()
    assert "self-hosted factory runner" in text
    assert "on every pull request" in text
    assert ".github/scripts/verify_tests.py" in text and (ROOT / ".github/scripts/verify_tests.py").is_file()
    # CI is tier 1: no deploy step, so no workflow deploys anything.
    assert "no deploy step" in text
    for file in (ROOT / ".github/workflows").glob("*.yml"):
        assert "deploy" not in file.read_text(encoding="utf-8").lower(), file.name


def test_ac6_the_doc_is_reachable_from_the_readme_and_from_the_agents_index():
    assert "docs/deployment.md" in read(README)
    index = section(read(AGENTS), "## Modular docs index")
    assert "`docs/deployment.md`" in index
    lines = [line for line in index.splitlines() if line.startswith("- `docs/")]
    assert len(lines) == len(list((ROOT / "docs").glob("*.md")))


def test_ac7_the_rubric_numbers_are_patch_4s():
    text = flat(read(DOC))
    for fact in RUBRIC:
        assert fact in text, fact
    assert "not 3 as `docs/spec.md` states" in text


def test_every_api_path_the_doc_names_is_a_path_the_seam_answers_on():
    text = read(DOC)
    named = {token.strip("/") for token in re.findall(r"api/[A-Za-z<]+(?:/[A-Za-z0-9<>]+)*", text)}
    allowed = seam_paths()
    for path in named:
        root = "/".join(path.split("/")[:2])
        assert path in allowed or root in allowed, path
    assert named, "the document names no seam path"


def test_the_document_is_english_and_carries_no_host_path_and_no_credential():
    text = read(DOC)
    assert not POSIX_ABSOLUTE.search(text), POSIX_ABSOLUTE.search(text)
    assert not WINDOWS_ABSOLUTE.search(text)
    assert not [m for m in SECRET_MARKERS if m in text], [m for m in SECRET_MARKERS if m in text]
    assert not [m for m in ITALIAN_MARKERS if m in text.lower()], text
    # No customer email either: the seed names the owner as a configured value, not as an address.
    assert not re.search(r"[\w.]+@[\w.]+\.[A-Za-z]{2,}", text), text
