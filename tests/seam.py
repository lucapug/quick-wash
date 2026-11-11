"""The HTTP client every rule test drives the seam through.

`client.session(email)` performs the sign-in once and returns a session object with `.headers` and
`.token`, so a test can tell who is asking on every later request. Responses record their body so
the pytest hook in tests/fixtures.py can print it when an assertion fails.

The two things the issue bodies write are what the client answers to: a session passed straight as
`headers=` (the mapping itself), and the body read as `.text()` as well as `.text`. Nothing in a test
is adjusted to fit the client.
"""

import json
import urllib.error
import urllib.request

try:  # the decision is httpx; the stdlib path keeps a clean checkout runnable without it
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class Text(str):
    """A response body that reads both ways.

    The tests written against an HTTP client read the body as `.text`; the tests in the issue bodies
    write `.text()`. A string that answers when called returns itself, so one Response satisfies both
    and a test is never adjusted to fit the client.
    """

    def __call__(self) -> str:
        return self


class Response:
    def __init__(self, status: int, body: str, headers: dict, request: str) -> None:
        self.status_code = status
        self.text = Text(body)
        self.headers = {key.lower(): value for key, value in headers.items()}
        self.request = request

    def json(self) -> dict:
        return json.loads(self.text)


class Session:
    """A sign-in reused across requests: the seam knows who is asking.

    A session is also the header mapping a request takes, because the tests write `headers=a` and not
    `headers=a.headers`: the session *is* the header that says who is asking, so `dict(session)` and
    `session.headers` are the same thing.
    """

    def __init__(self, email: str, token: str, otp: str) -> None:
        self.email = email
        self.token = token
        self.otp = otp
        self.headers = {"Authorization": f"Bearer {token}"}

    def keys(self) -> list:
        return list(self.headers)

    def items(self) -> list:
        return list(self.headers.items())

    def __getitem__(self, key: str) -> str:
        return self.headers[key]

    def __iter__(self):
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.headers)

    def __repr__(self) -> str:
        return f"<session {self.email}>"


class SeamClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.last_response: Response | None = None
        self._httpx = httpx.Client(base_url=base_url) if httpx else None

    def get(self, path, headers=None) -> Response:
        return self._request("GET", path, None, headers)

    def post(self, path, payload=None, headers=None, json=None) -> Response:
        # `json=` is accepted as the body so a test can post a literal payload the way the
        # HTTP clients in the issue bodies write it.
        return self._request("POST", path, payload if payload is not None else json, headers)

    def session(self, email: str) -> Session:
        """Sign in as `email`: ask for the code (shown in-app), then redeem it once for the token.

        The two steps are the two identity paths: `POST /api/session` takes the email only, and the code
        it showed is redeemed on `POST /api/session/verify` — the only thing that mints a session, which
        is why a caller that has not gone through it is not a customer (issue #9, AC7).
        """
        request = self.post("/api/session", {"email": email})
        otp = request.json()["otp"]
        verified = self.post("/api/session/verify", {"email": email, "otp": otp})
        payload = verified.json()
        if verified.status_code != 200 or not payload.get("token"):
            raise AssertionError(f"sign-in failed for {email}: {verified.text}")
        return Session(email, payload["token"], otp)

    def close(self) -> None:
        if self._httpx:
            self._httpx.close()

    def _request(self, method, path, payload, headers) -> Response:
        url = f"{self.base_url}{path}"
        sent = dict(headers or {})
        if payload is not None:
            sent["Content-Type"] = "application/json"
        if self._httpx:
            response = self._httpx.request(method, path, json=payload, headers=sent)
            recorded = Response(response.status_code, response.text, dict(response.headers), f"{method} {path}")
        else:
            data = json.dumps(payload).encode() if payload is not None else None
            request = urllib.request.Request(url, data=data, headers=sent, method=method)
            try:
                with urllib.request.urlopen(request) as raw:
                    recorded = Response(raw.status, raw.read().decode(), dict(raw.headers), f"{method} {path}")
            except urllib.error.HTTPError as error:
                recorded = Response(error.code, error.read().decode(), dict(error.headers), f"{method} {path}")
        self.last_response = recorded
        return recorded
