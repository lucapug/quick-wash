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
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from src.app import Application
from src.db import connect


def make_handler(app: Application):
    class SeamHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.answer("GET")

        def do_POST(self):
            self.answer("POST")

        def answer(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            query = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            status, payload = app.handle(method, self.path.split("?")[0], {**query, **body}, dict(self.headers))
            # A view read answers with the page itself: the front-end reads it as text, so a string payload
            # is written as text/html and not wrapped in quotes. Every other answer stays JSON — the seam the
            # tests drive is unchanged.
            raw = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if isinstance(payload, str)
                             else "application/json")
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
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
