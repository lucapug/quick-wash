// The app shell, in React (Vite), as the issue's Decision names it.
//
// It owns no copy: every string the customer reads arrives from `src/views.py` through the seam, and every
// action goes to the same HTTP seam the tests drive (`POST /api/session`, `POST /api/session/verify`,
// `POST /api/bookings`, `POST /api/machines/<code>/report`, `GET /api/views/<screen>`). There is no
// backend-for-frontend layer between the shell and the tested seam, so the shell cannot re-decide a rule:
// it displays what the seam decided, in the language the seam answered in.

import { useEffect, useState } from "react";

const SEAM = {
  session: "/api/session",
  verify: "/api/session/verify",
  booking: "/api/bookings",
  report: (code) => `/api/machines/${code}/report`,
  view: (screen) => `/api/views/${screen}`,
};

const FIRST_SCREEN = "availability";

export default function App() {
  const [session, setSession] = useState({ email: null, token: null });
  const [page, setPage] = useState(null);
  const [answer, setAnswer] = useState(null);

  const headers = () => (session.token ? { Authorization: `Bearer ${session.token}` } : {});

  async function call(method, path, body) {
    const response = await fetch(path, {
      method,
      headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...headers() },
      body: body ? JSON.stringify(body) : null,
    });
    const text = await response.text();
    try {
      return { status: response.status, body: JSON.parse(text) };
    } catch (notJson) {
      return { status: response.status, body: text };   // a view read answers with the page itself
    }
  }

  async function open(screen) {
    const response = await call("GET", SEAM.view(screen));
    setPage({ screen, status: response.status, body: response.body });
  }

  useEffect(() => { open(FIRST_SCREEN); }, []);

  // The nav is the seam's own: the labels and the links come from the page the seam answered with, never
  // from a copy this file keeps.
  function parse(pageBody) {
    if (typeof pageBody !== "string") return null;
    const doc = new DOMParser().parseFromString(pageBody, "text/html");
    return {
      brand: doc.querySelector(".navbar-brand").textContent,
      links: [...doc.querySelectorAll(".nav-link")].map((link) => ({
        href: link.getAttribute("href"),
        screen: link.getAttribute("href").replace("/api/views/", "").split("?")[0],
        label: link.textContent,
        active: link.classList.contains("active"),
      })),
      main: doc.querySelector("main").innerHTML,
    };
  }

  async function act(event) {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    const action = target.getAttribute("data-action");
    if (action === "sign-in") {
      const email = document.getElementById("email").value;
      const asked = await call("POST", SEAM.session, { email });
      // The one-time code is shown in-app (addendum patch 1): the answer is the delivery channel, so the
      // code the seam showed is redeemed straight from it. Nothing here reads an inbox.
      setAnswer({ status: asked.status, text: asked.body.message, shownInApp: asked.body.otp });
      const verified = await call("POST", SEAM.verify, { email, otp: asked.body.otp });
      if (verified.body.token) setSession({ email, token: verified.body.token });
      return;
    }
    if (action === "commit") {
      const result = await call("POST", SEAM.booking, {
        type: target.getAttribute("data-type"),
        start: target.getAttribute("data-start"),
      });
      setAnswer({ status: result.status, text: result.body.message });
      return;
    }
    if (action === "report") {
      const result = await call("POST", SEAM.report(target.getAttribute("data-machine")), {
        kind: target.getAttribute("data-kind"),
      });
      setAnswer({ status: result.status, text: result.body.message });
    }
  }

  const view = parse(page ? page.body : null);

  // Verdict fix (manual, needs-human path): while the view state is still null — the fetch inside the
  // effect has not answered yet — the component renders the loading shell, never a page built from a
  // state that is only a screen name. `parse` runs only on fetched text.
  if (!page) {
    return <main className="container py-4" data-screen={FIRST_SCREEN}><p>Loading availability…</p></main>;
  }

  return (
    <main className="container py-4" data-screen={page ? page.screen : null} onClick={act}>
      {view && (
        <nav className="navbar navbar-expand border-bottom mb-3">
          <span className="navbar-brand">{view.brand}</span>
          <ul className="nav">
            {view.links.map((link) => (
              <li className="nav-item" key={link.href}>
                <a className={`nav-link${link.active ? " active" : ""}`} href={link.href}
                   onClick={(event) => { event.preventDefault(); open(link.screen); }}>
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}
      {view && <div data-status={page.status} dangerouslySetInnerHTML={{ __html: view.main }} />}
      {answer && <p className="answer" data-status={answer.status}>{answer.text}</p>}
    </main>
  );
}
