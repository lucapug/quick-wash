"""The static mount: the built front-end, served by the same application that answers the API.

Two facts fix the shape of this module.

1. **The mount reads an artifact, it does not render a page.** What it serves is the build output of
   `src/frontend` (`npm ci && npm run build` in the container), and that output is committed in the
   repository. A reviewer clones and runs: no toolchain, no install, no `npm` — the app is what the
   checkout carries. The committed artifact is a fact of `src/frontend/package.json` and its lockfile,
   so it is reproducible from the source rather than a page written by hand.
2. **The mount is not a second decision layer.** It owns every path outside `/api/`: it resolves a file
   inside `dist/` and answers with it, nothing else. `/api/*` stays the seam the tests drive — the eight
   contract paths `tests/conftest.py` pins plus their patterns. The copy the app writes lives in
   `src/views.py`; a static read adds no string of its own, so there is nothing here that a rule could
   disagree with.

Four things the mount deliberately does not do, each one an observable outcome:

- **It does not write.** Only `GET` reads it; any other method on a mount path is refused (405). A file
  is not a seam entry, and the seam's writes stay the seam's.
- **It does not read outside itself.** A path that resolves outside `dist/` is not a file that is there
  (404), so the mount is not a file reader for the repository. `..` is decoded, resolved and refused.
- **It is not part of the contract.** `ROUTES` stays the eight entries `tests/conftest.py` pins; a static
  read is a presentation read, not a contract path. `GET /api/<anything>` is therefore never answered by
  the mount, and the app's own 404 for a path it does not know is untouched.
- **It does not enter telemetry.** `src/telemetry.py` records request lines and guards them against the
  shape of a credential — four digits or more is the shape of both codes. A build asset name is a content
  hash: its digits are that same shape, so a static read would either be refused by the guard or would put
  a filename where a journey line belongs. The guard is not loosened for the mount; the mount stays out of
  the recorder.

There is no single-page fallback: the shell has no router of its own (its screens are a query on the
seam's read, not a path), so `/` answers the entry file and a path that is not a file is simply not there.
"""

import pathlib
from urllib.parse import unquote

# The artifact, as the checkout carries it: the build output of `src/frontend`. `DIST` is the folder, the
# constant below is the same folder written the way every path in this project is written — repository-
# relative, never a host path, including in the message a refusal answers with.
DIST = pathlib.Path(__file__).resolve().parent / "frontend" / "dist"
DIST_PATH = "src/frontend/dist"
INDEX = "index.html"

# The line between the two readers of the same app: the mount owns what is outside the seam.
API = "/api/"

# Content type per extension. Only `application/json` and `text/html; charset=utf-8` are the seam's own;
# everything else here is what the browser needs to read the file as itself.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
}

JSON = "application/json"


def content_type(path: pathlib.Path) -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def artifact(root: pathlib.Path = DIST) -> dict:
    """What the checkout carries, read as data: the entry file and the files next to it."""
    if not (root / INDEX).is_file():
        return {"root": DIST_PATH, "entry": None, "files": []}
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    return {"root": DIST_PATH, "entry": INDEX, "files": files}


def resolve(path: str, root: pathlib.Path = DIST) -> pathlib.Path | None:
    """The file the mount owns for `path`, or None when it is not a file inside the mount.

    The query is not part of the file. The path is decoded before it is resolved, because a percent-encoded
    `..` is the same path as a plain one: whatever resolves outside `dist/` is not something the mount has.
    """
    name = unquote(path.split("?")[0]).strip("/")
    candidate = (root / name).resolve() if name else (root / INDEX).resolve()
    if root.resolve() not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def read(method: str, path: str, root: pathlib.Path = DIST) -> tuple | None:
    """The answer to a request the mount owns, or None when the backend owns it.

    `None` is the hand-off: the path belongs to `src/app.py`, so the seam answers it. A number with a body
    is an answer, so the caller never has to guess who decided it.
    """
    if path.startswith(API):
        return None
    if method != "GET":
        # The mount is a read: it has no write surface, so a method that would change something is refused
        # rather than performed on a file.
        return 405, {"error": "method_not_allowed",
                     "message": "Il mount statico legge solo: non scrive"}, JSON
    file = resolve(path, root)
    if file is None:
        if not (root / INDEX).is_file():
            # The artifact is the deliverable: when it is not in the checkout the app is not there.
            return 404, {"error": "artifact_missing", "root": DIST_PATH, "path": path,
                         "message": f"L'artefatto costruito non è nel repository: {DIST_PATH}"}, JSON
        return 404, {"error": "not_found", "message": f"Percorso sconosciuto: {path}"}, JSON
    return 200, file.read_bytes(), content_type(file)
