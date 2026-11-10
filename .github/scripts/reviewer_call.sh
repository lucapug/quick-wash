#!/bin/sh
# Review indipendente: GLM-Z1-9B-0414 (reasoning) RESIDENTE su Minisforum :8081
# (GPU 3070 sempre accesa dal 06/11 — ADR 0003 emendata per-GPU; GLM-4.7-Flash in
# finestra su 3090 resta fallback manuale con stop residente preliminare).
# Il fallback "pi su Strata" e' RIMOSSO: stesso modello dell'autore = bypass
# strutturale del gate (lezione ciclo #18). Reviewer giu o content vuoto
# (reasoning loop / budget token) = VERDICT: NEEDS_HUMAN — mai approvazione implicita.
# Credenziali: REVIEWER_API_KEY via env (runner .env); header via file temporaneo,
# mai in argv (igiene segreti, skill strata-key-rotation).
# Uso: sh reviewer_call.sh <file-prompt> <file-out>
#      → stampa a stdout il reviewer usato ("glm-z1-9b-0414" | "needs-human")
set -u

PROMPT="${1:?manca il file prompt}"
OUT="${2:?manca il file out}"
REVIEWER="needs-human"

REQ="$(mktemp)"; HDR="$(mktemp)"; RESP="$(mktemp)"
trap 'rm -f "$REQ" "$HDR" "$RESP"' EXIT

printf 'header = "Authorization: Bearer %s"\n' "${REVIEWER_API_KEY:-}" > "$HDR"

needs_human() {
  cat > "$OUT" <<'EOF'
VERDICT: NEEDS_HUMAN
Reviewer non raggiungibile oppure risposta incompleta (content vuoto / errore).
Niente fallback pi: sarebbe lo stesso modello dell'autore. Review a mano;
verificare lo stato del residente Z1 su Minisforum :8081.
EOF
}

# pre-check rapido: il residente e sempre up, se muta e un allarme vero —
# needs-human subito senza attendere il timeout della review completa
if ! curl -s --max-time 8 -K "$HDR" "${REVIEWER_BASE_URL%/}/models" -o /dev/null 2>/dev/null; then
  needs_human
  echo "$REVIEWER"
  exit 0
fi

python3 - "$PROMPT" > "$REQ" <<'PY'
import json, sys
print(json.dumps({
    "model": "glm-z1-9b-0414",
    "messages": [{"role": "user", "content": open(sys.argv[1]).read()}],
    "temperature": 0.2,
    "max_tokens": 4000,
}))
PY

if curl -s --max-time 240 -K "$HDR" \
     --data-binary @"$REQ" \
     "${REVIEWER_BASE_URL%/}/chat/completions" \
     -o "$RESP" 2>/dev/null \
   && python3 - "$RESP" "$OUT" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    c = (d["choices"][0]["message"] or {}).get("content") or ""
except Exception:
    sys.exit(1)
if not c.strip():
    sys.exit(1)
# Z1 apre il content con newline: il workflow fa head -1 sul verdetto,
# quindi gli spazi iniziali vanno tolti o ogni review risulterebbe rifiutata
open(sys.argv[2], "w").write(c.lstrip())
PY
then
  REVIEWER="glm-z1-9b-0414"
fi

if [ "$REVIEWER" = "needs-human" ]; then
  needs_human
fi

echo "$REVIEWER"
