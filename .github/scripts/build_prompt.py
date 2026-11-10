#!/usr/bin/env python3
"""Costruisce il prompt di implementazione per pi a partire dall'issue JSON."""
import json
import sys

d = json.load(open(sys.argv[1]))
print(f"""Titolo: {d['title']}

{d['body']}

REGOLE OPERATIVE:
- Implementazione in src/, test in tests/ (il file di test fornito nell'issue va creato ESATTAMENTE come dato: non modificarlo).
- I test importano con 'from src.<modulo> import ...'; pytest.ini ha pythonpath=. e testpaths=tests.
- Lavora finche' 'python3 -m pytest -q' non passa completamente.
- Non toccare file fuori da src/ e tests/.""")
