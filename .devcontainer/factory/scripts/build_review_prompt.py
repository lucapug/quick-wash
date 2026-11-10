#!/usr/bin/env python3
"""Costruisce il prompt di review per il reviewer indipendente (pi; issue + diff)."""
import json
import sys

issue = json.load(open(sys.argv[1]))
diff = open(sys.argv[2]).read()

print(f"""Sei il reviewer indipendente di una factory di agenti. Valuta la PR che chiude l'issue seguente.

== ISSUE ==
Titolo: {issue['title']}

{issue['body']}

== DIFF (origin/main...head) ==
{diff}
== FINE DIFF ==

ISTRUZIONI:
- Puoi eseguire 'python3 -m pytest -q' per verificare indipendentemente (sei nel workspace della PR).
- Confronta il diff con gli acceptance criteria dell'issue: correttezza, test rispettati, assenza di modifiche ai test forniti, assenza di file toccati fuori scope.
- NON modificare alcun file.
- Prima riga della risposta, esattamente: 'VERDICT: APPROVED' oppure 'VERDICT: CHANGES_REQUESTED'.
- Poi le tue osservazioni puntuali (max ~200 parole). Se rimandi, dì chiaramente cosa chiedi a chi ha implementato.""")
