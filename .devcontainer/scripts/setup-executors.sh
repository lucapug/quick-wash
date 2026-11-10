#!/bin/sh
# Factory V1 — setup esecutori + bootstrap della pipeline nel progetto.
# SPEC 0001: la fonte unica della chiave è il .env del runner (permessi 600, un
# solo file); l'env di creazione del container non la contiene più. I config
# letterali degli esecutori (classe 2) sono risolti da questa fonte a OGNI
# esecuzione: una scrittura guardata da `[ ! -f ]` non riallinea mai un file già
# esistente, quindi qui si scrive sempre.
# Uscita di rete solo tramite il gate squid (allowlist in ../squid/squid.conf).
set -e
DC="$(cd "$(dirname "$0")/.." && pwd)"     # .devcontainer/
ROOT="$(cd "$DC/.." && pwd)"               # root del progetto

# --- 0. bootstrap della pipeline V2 (idempotente: non sovrascrive) ---
# SEGRETO-FREE: la copia precede il check della chiave, quindi su un'istanza
# nuova i file pipeline nascono (e sono committabili) anche senza .env; la
# semantica SPEC 0001 "nessun config scritto senza chiave" resta intatta — il
# check segue, i config degli esecutori si scrivono solo con chiave risolta.
mkdir -p "$ROOT/.github/workflows" "$ROOT/.github/scripts"
for w in "$DC/factory/workflows/"*.yml; do
  cp -n "$w" "$ROOT/.github/workflows/" 2>/dev/null || true
done
for s in classify.py build_prompt.py build_review_prompt.py verify_tests.py reviewer_call.sh; do
  cp -n "$DC/factory/scripts/$s"                   "$ROOT/.github/scripts/" 2>/dev/null || true
done
cp -n "$DC/factory/pytest.ini"                     "$ROOT/" 2>/dev/null || true
cp -n "$DC/factory/opencode.json"                  "$ROOT/" 2>/dev/null || true
echo "bootstrap: workflow V2 (route-issue, pi-issue, pi-review, factory-merge) + pytest.ini + opencode.json (committali; poi vedi .devcontainer/factory/BOOTSTRAP.md)"

# --- 1. Fonte unica: .env del runner (config degli esecutori) ---
RUNNER_ENV="${RUNNER_ENV:-$HOME/actions-runner/.env}"
if [ -f "$RUNNER_ENV" ]; then
  # '.' e' builtin speciale: con set -e un source fallito fa exit prima di
  # '(eval) || true' — va protetto con un if, non con '||'.
  set -a; . "$RUNNER_ENV"; set +a
fi
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY non risolta da $RUNNER_ENV." >&2
  echo "  File pipeline copiati; nessun config scritto. Il .env va ripristinato" >&2
  echo "  PRIMA dei config degli esecutori dopo ogni ricreazione del container" >&2
  echo "  (Stage 5 golden path: apply/restore-runner-env.sh, chiavi dal portachiavi" >&2
  echo "  via stdin, permessi 600), poi rieseguire questo script." >&2
  exit 1
fi
umask 077   # i file generati non ereditano la modalità della shell del container

# --- 2. OpenCode ---
npm install -g opencode-ai
mkdir -p ~/.local/share/opencode
printf '{"strata":{"type":"api","key":"%s"}}' "$OPENAI_API_KEY" > ~/.local/share/opencode/auth.json

# --- 3. pi (coding agent) ---
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
mkdir -p ~/.pi/agent
cat > ~/.pi/agent/models.json <<'JSON'
{
  "$schema": "https://pi.dev/schemas/models.schema.json",
  "providers": {
    "strata": {
      "baseUrl": "http://minisforum-nucx-windows.tail60fef8.ts.net:8080/v1",
      "api": "openai-completions",
      "apiKey": "${OPENAI_API_KEY}",
      "models": [
        { "id": "qwen3.8-flash-next-iq2_xs", "contextWindow": 262144 }
      ]
    }
  }
}
JSON

# --- 4. prime-agent (PrimeIntellect, RLM) ---
curl -fsSL https://app.primeintellect.ai/prime-agent/install.sh | sh
curl -LsSf https://astral.sh/uv/install.sh | sh
python3 -m pip install --break-system-packages -q pytest ipykernel || true
python3 - <<PY
import json, os
p = os.path.expanduser("~/.prime/agent/models.json")
os.makedirs(os.path.dirname(p), exist_ok=True)
d = {}
try: d = json.load(open(p))
except Exception: pass
d["providers"] = d.get("providers", {})
d["providers"]["strata"] = {
    "baseUrl": os.environ["LOCAL_LLM_BASE_URL"],
    "api": "openai-completions",
    "apiKey": os.environ["OPENAI_API_KEY"],
    "models": [{"id": "qwen3.8-flash-next-iq2_xs", "contextWindow": 262144}],
}
json.dump(d, open(p, "w"), indent=1)
print("prime-agent: provider strata configurato")
PY
export PATH="$HOME/.local/bin:$PATH"

# l'umask governa solo i file NUOVI: sovrascrivere un file già esistente ne
# conserva la modalità, quindi i tre config vanno normalizzati esplicitamente
# (un generatore idempotente non ripara un file nato 666).
for f in ~/.local/share/opencode/auth.json ~/.pi/agent/models.json ~/.prime/agent/models.json; do
  [ -f "$f" ] && chmod 600 "$f"
done

# --- 5. probe (si attende la parola PONTE da ciascun esecutore) ---
opencode run --model strata/qwen3.8-flash-next-iq2_xs "Rispondi solo: PONTE"
pi -p --no-session --provider strata --model qwen3.8-flash-next-iq2_xs "Rispondi solo: PONTE"
prime-agent -p --no-session --provider strata --model qwen3.8-flash-next-iq2_xs "Rispondi solo: PONTE"
echo "factory V1: esecutori pronti (opencode, pi, prime-agent)"
