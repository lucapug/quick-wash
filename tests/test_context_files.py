"""Checks on the project context files created by this issue (README.md, AGENTS.md)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PACK = {"docs/spec.md", "docs/addendum-firma.md"}

POSIX_ABSOLUTE = re.compile(r"(?<![\w.'])/(?:[\w.-]+/)+")
WINDOWS_ABSOLUTE = re.compile(r"[A-Za-z]:\\\\[\w.-]")
ITALIAN_MARKERS = ("è", "é", "ò", "à", "ì", "ù", "perché", "nell'", "dell'", "dalla",
                   "delle", "cartella", "viaggia", "documento di progetto")
SECRET_MARKERS = ("gho_", "ghp_", "sk-", "token=", "secret=", "key=", "-----BEGIN")


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """One section of a markdown file: from a heading to the next heading."""
    start = text.index(heading)
    rest = text[start + len(heading):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def test_readme_is_english_and_states_the_purpose():
    text = read("README.md")
    assert "quick-wash" in text
    assert not [m for m in ITALIAN_MARKERS if m in text.lower()]


def test_readme_documents_the_one_command_start_and_the_single_test_command():
    text = read("README.md").lower()
    assert "docker compose up" in text
    assert "pytest" in text


def test_readme_links_the_authoritative_pack():
    text = read("README.md")
    assert "docs/spec.md" in text
    assert "docs/addendum-firma.md" in text


def test_readme_lists_only_the_pack_as_authoritative_specs():
    table = section(read("README.md"), "## Authoritative spec layer")
    rows = [line for line in table.splitlines() if line.startswith("| [docs/")]
    assert len(rows) == len(PACK)
    assert "AGENTS.md" not in table


def test_docs_folder_contains_only_the_pack_and_the_record():
    found = {f"docs/{p.name}" for p in DOCS.glob("*.md")}
    assert found == PACK | {"docs/ESITO.md"}


def test_agents_declares_the_pack_as_the_authoritative_layer_and_the_addendum_wins():
    text = read("AGENTS.md")
    layer = section(text, "## Authoritative spec layer")
    assert "docs/spec.md" in layer
    assert "docs/addendum-firma.md" in layer
    assert "wins on every conflict" in layer
    for fact in ("10 minutes", "30 minutes", "out of scope", "5/24", "in-app"):
        assert fact in layer
    assert "Italian" in text
    assert "English" in text


def test_agents_indexes_every_modular_doc_under_docs():
    index = section(read("AGENTS.md"), "## Modular docs index")
    lines = [line for line in index.splitlines() if line.startswith("- `docs/")]
    assert len(lines) == len(list(DOCS.glob("*.md")))
    for path in sorted(DOCS.glob("*.md")):
        assert f"`docs/{path.name}`" in index
    assert "AGENTS.md" not in index


def test_index_lines_are_repo_relative_and_point_at_real_files():
    index = section(read("AGENTS.md"), "## Modular docs index")
    for line in (line for line in index.splitlines() if line.startswith("- `docs/")):
        path = line.split("`")[1]
        assert not path.startswith("/")
        assert (ROOT / path).is_file()


def test_context_files_have_no_host_paths_and_no_secrets():
    for name in ("README.md", "AGENTS.md"):
        text = read(name)
        assert not POSIX_ABSOLUTE.search(text), name
        assert not WINDOWS_ABSOLUTE.search(text), name
        assert not [m for m in SECRET_MARKERS if m in text], name
        assert not [m for m in ITALIAN_MARKERS if m in text.lower()], name
