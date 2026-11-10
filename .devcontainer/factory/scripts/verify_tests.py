#!/usr/bin/env python3
"""Tamper-check: i test forniti nell'issue devono arrivare byte-identici nella PR.

Convenzione: nel corpo dell'issue ogni test fornito è un fenced block il cui
info string contiene il percorso repo del file, es. ```python tests/test_x.py
Confronto sha256 tra il contenuto del block e il file nel workspace (checkout
della PR head). Exit 0 = tutti identici (o nessun test fornito, check non
applicabile); exit 1 = file mancante o modificato (il workflow blocca).
"""
import hashlib
import json
import re
import sys

FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.M | re.S)


def provided_tests(body):
    for m in FENCE.finditer(body):
        for token in m.group(1).split():
            if re.match(r"^[\w.-]+/[\w./-]+$", token):
                yield token, m.group(2)


def main():
    issue = json.load(open(sys.argv[1]))
    blocks = list(provided_tests(issue.get("body") or ""))
    if not blocks:
        print("tamper: nessun test fornito nell'issue (check non applicabile)")
        return 0
    rc = 0
    for path, content in blocks:
        want = hashlib.sha256(content.encode()).hexdigest()
        try:
            with open(path, "rb") as f:
                have = hashlib.sha256(f.read()).hexdigest()
        except FileNotFoundError:
            print(f"tamper: FAIL {path} — mancante nel workspace della PR (spec sha256 {want[:12]})")
            rc = 1
            continue
        if want == have:
            print(f"tamper: OK {path} (sha256 {want[:12]})")
        else:
            print(f"tamper: FAIL {path} — modificato (spec {want[:12]} vs repo {have[:12]})")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
