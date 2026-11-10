#!/usr/bin/env python3
"""System-one router: classifica un issue atomic/complex con Strata (json_schema).

Input da env: ISSUE_TITLE, ISSUE_BODY, OPENAI_API_KEY, LOCAL_LLM_BASE_URL.
Output (stdout, formato GITHUB_OUTPUT): route=, confidence=, reason=.

Politica: override manuale col prefisso [atomic]/[complex] nel titolo;
confidence < 0.75 o risposta invalida -> default 'complex' (direzione sicura:
al team costa processo, a pi un task complesso rischia un pasticcio).
"""
import json
import os
import urllib.request

TITLE = (os.environ.get("ISSUE_TITLE") or "").strip()
BODY = (os.environ.get("ISSUE_BODY") or "").strip()

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "routing",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "route": {"type": "string", "enum": ["atomic", "complex"]},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["route", "confidence", "reason"],
            "additionalProperties": False,
        },
    },
}

SYSTEM = (
    "Sei il router di una factory di agenti. Classifica il task di coding: "
    "'atomic' se e' un intervento chirurgico su un repo esistente (pochi file, "
    "criteri chiari, nessuna decisione architetturale); 'complex' se richiede "
    "pianificazione, piu' passi, decisioni architettoniche, un nuovo progetto "
    "o un refactoring. Rispondi SOLO col JSON richiesto."
)


def emit(route, confidence, reason):
    if route not in ("atomic", "complex") or confidence < 0.75:
        route = "complex"
        reason = f"[fallback soglia, conf={confidence:.2f}] {reason}"
    print(f"route={route}")
    print(f"confidence={confidence:.2f}")
    print(f"reason={reason}")


low = TITLE.lower()
if low.startswith("[atomic]"):
    emit("atomic", 1.0, "override manuale [atomic] nel titolo")
elif low.startswith("[complex]"):
    emit("complex", 1.0, "override manuale [complex] nel titolo")
else:
    payload = {
        "model": "qwen3.8-flash-next-iq2_xs",
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Titolo: {TITLE}\n\n{BODY}"},
        ],
        "response_format": SCHEMA,
        "max_tokens": 200,
    }
    import time
    import urllib.error

    url = os.environ["LOCAL_LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    last_err = None
    d = None
    for attempt in range(3):
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r)
            break
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            last_err = e
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    if d is None:
        raise SystemExit(f"classify: endpoint non raggiungibile dopo 3 tentativi: {last_err}")
    decision = json.loads(d["choices"][0]["message"]["content"])
    emit(
        decision.get("route"),
        float(decision.get("confidence", 0.0)),
        decision.get("reason", ""),
    )
