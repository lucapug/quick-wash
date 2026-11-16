"""HTTP binding for the seam.

The application object is framework-neutral: this module is the only place that turns a request
into a call on `Application.handle`. The test fixture starts the same server on 127.0.0.1 with an
ephemeral port, so a test drives the real HTTP boundary without anyone starting a service by hand.

Telemetry here is the request line only: no body, no customer email, no unlock code, no one-time
code (docs/spec.md, Observability shape). The query parameters of the public read (`window_hours`,
`type`) join the body of the call, and the logged line is the path without them. The line itself is
written by `src/telemetry.py`, because that is where the credential guard lives: a line that would
carry a credential is refused before it is stored or printed, so nothing here can log one.

Every contract entry answers with JSON. A view read (issue #20, `src/views.py`) answers with the page
itself, so a string payload is written as text/html and not wrapped in quotes: the seam, the handlers,
the statuses and the entitlements are the same, and the front-end reads both the same way.

This module is also where the front-end is mounted (issue #69): the same handler answers a path outside
`/api/` with the committed build artifact through `src/static.py`, and a path inside it with the app. One
process serves both, so the reviewer's run is one command — `python3 -m src.server` — and the page and the
API it talks to are the same application. `ROUTES` is not extended for it: the mount is not a contract path,
and the eight entries `tests/conftest.py` pins are answered by the backend.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from src import static
from src.app import Application
from src.db import connect


def make_handler(app: Application):
    """One handler, two readers: the seam decides, the mount reads a file.

    The split is one line and it is the whole of the mount: a path outside `/api/` is answered by
    `src/static.py` from the committed artifact, a path inside it is answered by `Application.handle` exactly
    as before. The same process, the same app object, the same port — the front-end is served by the backend
    that already answers the API, so there is no second service to start and no second place a rule could be
    decided. The hand-off is `static.read` answering `None`: the mount knows it does not own an API path, so
    the eight contract paths `tests/conftest.py` pins and their patterns are untouched, and the seam is still
    the only entry point.
    """
    class SeamHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.answer("GET")

        def do_POST(self):
            self.answer("POST")

        def answer(self, method):
            path = self.path.split("?")[0]
            served = static.read(method, path)
            if served is not None:
                status, payload, content_type = served
                self.write(status, payload, content_type)
                return
            length = int(self.headers.get("Content-Length") or 0)
            query = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            status, payload = app.handle(method, path, {**query, **body}, dict(self.headers))
            self.write(status, payload)

        def write(self, status, payload, content_type=None):
            # A view read answers with the page itself: the front-end reads it as text, so a string payload
            # is written as text/html and not wrapped in quotes. A static read answers with the bytes of the
            # artifact, and the response is written the same way. Every other answer stays JSON — the seam the
            # tests drive is unchanged.
            if isinstance(payload, bytes):
                raw = payload
            elif isinstance(payload, str):
                raw = payload.encode()
                content_type = content_type or "text/html; charset=utf-8"
            else:
                raw = json.dumps(payload).encode()
                content_type = content_type or "application/json"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):  # the structured line is the log, and the recorder writes it
            pass

    return SeamHandler


def serve(app: Application, host: str = "127.0.0.1", port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    return server, server.server_address[1]


def main() -> None:
    app = Application(connect())
    server, port = serve(app, port=int(os.environ.get("PORT", "8000")))
    print(f"quick-wash listening on http://127.0.0.1:{port}")
    # The same process answers the app at the root and the API under `/api/`: the run from a clean checkout
    # needs no toolchain because the artifact is in the checkout (issue #69).
    print(f"the built app is served at / from {static.DIST_PATH}" if static.artifact()["entry"]
          else f"the built app is not in the checkout: run the build in {static.DIST_PATH}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
