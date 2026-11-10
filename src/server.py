"""HTTP binding for the seam.

The application object is framework-neutral: this module is the only place that turns a request
into a call on `Application.handle`. The test fixture starts the same server on 127.0.0.1 with an
ephemeral port, so a test drives the real HTTP boundary without anyone starting a service by hand.

Telemetry here is the request line only: no body, no customer email, no unlock code, no one-time
code (docs/spec.md, Observability shape).
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            status, payload = app.handle(method, self.path.split("?")[0], body, dict(self.headers))
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format, *args):  # request line only, never the body
            print(f"{self.address_string()} {self.command} {self.path.split('?')[0]}")

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
