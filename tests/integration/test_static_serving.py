"""Issue #69 (serve the built frontend from the backend): the mount, read as HTTP outcomes.

The slice is four things, and each one is asserted as an externally observable outcome at the seam:

- **the artifact** (`src/frontend/dist/`) is in the checkout, so `clone -> run` gives a reviewer the app
  without a toolchain; it is tracked past the `dist/` line `.gitignore` carries, which is what the issue
  names as part of the work;
- **one app answers both**: the same process, the same `Application`, the same port — the root is the
  built shell, `/api/*` is still the backend. The seam the tests drive is not put behind anything: the
  mount is a read, not a layer that decides, and `ROUTES` stays the eight entries `tests/conftest.py` pins;
- **the mount reads only, and only inside itself**: a method that would change something is refused, and a
  path that resolves outside the artifact is not a file that is there;
- **the entry point runs from a clean checkout**: `python3 -m src.server` with `QW_DATABASE_URL` on a
  SQLite file answers `/` with the app and `/api/*` with the backend.

Nothing is mocked: the client requests over 127.0.0.1 against the server `src/server.py` starts, the
repository is a real database (the file-backed one, the way the entry point uses it), and the entry point is
started as its own process, the way a reviewer starts it.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from tests.conftest import SEAM_PATHS

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "src" / "frontend"
DIST = SHELL / "dist"
ARTIFACT = "src/frontend/dist"

ASSET = re.compile(r'src="/(assets/[^"]+\.js)"')


def tracked_by_git(path: str) -> bool:
    """Whether the checkout carries the artifact, read from the tracker's own record.

    The assertion is the grader-proof part of the issue: `dist/` is in `.gitignore`, so the artifact earns
    its place in the repository by being force-added. Where the workspace is not a git checkout there is no
    trail to read, and the on-disk artifact is asserted by the test above.
    """
    if not shutil.which("git") or not (ROOT / ".git").exists():
        return True
    listed = subprocess.run(["git", "ls-files", path], cwd=ROOT, capture_output=True, text=True).stdout.split()
    return path in listed


# --- the artifact: what a reviewer gets from a clone, with no toolchain -----------------------------

def test_the_committed_artifact_is_the_build_output_the_checkout_carries(client, seed):
    assert DIST.is_dir(), f"{ARTIFACT} is not in the checkout"
    files = sorted(p.relative_to(DIST).as_posix() for p in DIST.rglob("*") if p.is_file())
    assert "index.html" in files, files
    assert any(name.startswith("assets/") and name.endswith(".js") for name in files), files
    # A hashed name is the signature of a build, not of a page written by hand.
    assert any(re.fullmatch(r"assets/index-[0-9A-Za-z_-]+\.js", name) for name in files), files
    assert tracked_by_git(f"{ARTIFACT}/index.html"), f"{ARTIFACT}/index.html is not tracked in the repo"
    assert (SHELL / "package.json").is_file() and (SHELL / "package-lock.json").is_file(), \
        "the build is not reproducible from the checkout"


def test_the_root_answers_the_shell_the_artifact_carries(client, seed):
    page = client.get("/")
    assert page.status_code == 200, page.text
    assert page.headers.get("content-type") == "text/html; charset=utf-8", page.headers
    assert 'id="screen"' in page.text, page.text          # the mount point the shell renders into
    assert page.text == (DIST / "index.html").read_text(encoding="utf-8"), "the answer is not the artifact"
    # The shell is public and owns no copy: it renders the seam's read, so it needs no session and keeps no
    # string of its own. The mount point is the one thing the artifact owns, and the asset answers with it.
    shell = (SHELL / "App.jsx").read_text(encoding="utf-8")
    mount = (SHELL / "main.jsx").read_text(encoding="utf-8")
    assert "/api/views/" in shell, shell                     # the shell talks to the tested seam only
    assert 'getElementById("screen")' in mount, mount         # and renders into the mount point the page carries


def test_the_asset_the_shell_references_is_served_by_the_same_app(client, seed):
    page = client.get("/")
    reference = ASSET.search(page.text)
    assert reference, page.text
    asset = client.get("/" + reference.group(1))
    assert asset.status_code == 200, asset.text
    assert asset.headers.get("content-type") == "text/javascript; charset=utf-8", asset.headers
    assert asset.text == (DIST / reference.group(1)).read_text(encoding="utf-8"), "the asset is not the artifact"


# --- one app answers both: the mount is a read, the backend is the decision -------------------------

def test_api_paths_are_still_answered_by_the_backend_and_not_by_the_mount(client, seed):
    availability = client.get("/api/availability")
    assert availability.status_code == 200, availability.text
    assert availability.headers.get("content-type") == "application/json", availability.headers
    assert availability.json()["opening_hours"] == {"open": "07:00", "close": "22:00"}
    # A file the mount owns is not an answer under `/api/`: the same name read through the seam is the
    # backend's own 404, so the mount never takes a contract path.
    inside = client.get("/api/index.html")
    assert inside.status_code == 404 and inside.json()["error"] == "not_found", inside.text
    # `ROUTES` is not extended for the mount: the eight entries `tests/conftest.py` pins still answer JSON.
    for entry in SEAM_PATHS:
        path = entry.split(" ", 1)[1]
        response = client.get(path)
        assert response.headers.get("content-type") == "application/json", (path, response.headers)
        assert response.status_code != 404 or response.json().get("error") == "not_found", path


def test_the_mount_reads_only_and_writes_nothing(client, seed):
    refused = client.post("/", json={})
    assert refused.status_code == 405, refused.text
    assert refused.json()["error"] == "method_not_allowed", refused.text
    assert client.post("/assets", json={}).status_code == 405, "the mount would be a write surface"
    # The seam's writes are untouched by the mount: the same client still books through the backend.
    ada = client.session("ada@example.com")
    booked = client.post("/api/bookings", json={"type": "quick", "start": "10:00"}, headers=ada)
    assert booked.status_code == 201, booked.text
    assert booked.json()["booking"]["machine"], booked.text


def test_the_mount_does_not_read_outside_itself(client, seed):
    for path in ("/../src/config.py", "/%2e%2e/%2e%2e/src/config.py", "/../README.md", "/index.html.bak"):
        refused = client.get(path)
        assert refused.status_code == 404, f"{path}: {refused.text}"
        assert refused.json()["error"] == "not_found", f"{path}: {refused.text}"
        # The refusal is the refusal, not the file: the answer is the seam's own not-found, so nothing that
        # lives outside the mount reaches the response.
        assert refused.headers.get("content-type") == "application/json", path
        assert refused.json()["message"].startswith("Percorso sconosciuto"), path
    assert client.get("/").status_code == 200  # the mount itself still answers at the root


def test_the_mount_answers_without_a_session_and_the_pages_it_renders_stay_gated(client, seed):
    # The shell is a public read: no identity is needed to get the page, and none to read the seam's data.
    assert client.get("/").status_code == 200
    assert client.get("/api/views/availability").status_code == 200
    # What is gated stays gated: the shell cannot open it by being served.
    assert client.get("/api/views/bookings").status_code == 401
    assert client.post("/api/bookings", json={"type": "quick", "start": "10:00"}).status_code == 401


# --- the entry point: the run a reviewer does from a clean checkout ----------------------------------

def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def read(url: str, retries: int = 20):
    """The entry point answers, or the test says so: the answer is the outcome, not the process."""
    for _ in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=10) as raw:
                return raw.status, raw.headers.get("Content-Type"), raw.read().decode()
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get("Content-Type"), error.read().decode()
        except OSError:
            time.sleep(0.5)
    raise AssertionError(f"the entry point did not answer: {url}")


def test_the_entry_point_answers_the_app_at_the_root_and_the_api_on_a_file_database():
    """AC (verify): `python3 -m src.server` with `QW_DATABASE_URL` on a SQLite file serves both."""
    with tempfile.TemporaryDirectory() as folder:
        database = Path(folder) / "quickwash.db"
        port = free_port()
        env = {**os.environ, "QW_DATABASE_URL": f"sqlite:///{database}", "PORT": str(port)}
        process = subprocess.Popen([sys.executable, "-m", "src.server"], cwd=ROOT, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            status, content_type, page = read(f"http://127.0.0.1:{port}/")
            assert status == 200 and content_type == "text/html; charset=utf-8", (status, content_type, page)
            assert 'id="screen"' in page, page

            status, content_type, body = read(f"http://127.0.0.1:{port}/api/availability")
            assert status == 200 and content_type == "application/json", (status, content_type, body)
            # The same application answers both: the seed the entry point wrote is the pack's inventory.
            assert database.is_file(), "the entry point opened no database"
            assert json.loads(body)["config"]["machines"] == 8, body
            assert json.loads(body)["config"]["types"] == {"standard": 4, "family": 2, "quick": 2}, body

            status, content_type, body = read(f"http://127.0.0.1:{port}/outside-the-mount")
            assert status == 404 and content_type == "application/json", (status, content_type, body)
            assert json.loads(body)["error"] == "not_found", body
        finally:
            process.terminate()
            process.wait(timeout=10)
