#!/bin/sh
# Factory V1 — GitHub Actions self-hosted runner nel container (rete labnet, via gate).
# Il repo si ricava da git remote (nessun hardcode). Uso, DENTRO il container app:
#   REG_TOKEN=... sh .devcontainer/scripts/setup-runner.sh
# Il token si genera dal Mac (o dove c'e' gh autenticato):
#   gh api -X POST repos/<owner>/<repo>/actions/runners/registration-token --jq .token
# Idempotente: se già configurato, si limita ad avviare run.sh.
set -e

DIR="$HOME/actions-runner"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO_SLUG="$(git -C "$ROOT" remote get-url origin | sed -E 's#.*github.com[:/]##; s#\.git$##')"
REPO_URL="https://github.com/$REPO_SLUG"
echo "runner per: $REPO_URL"

if [ ! -f "$DIR/.runner" ]; then
  mkdir -p "$DIR"
  cd "$DIR"
  VER="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | python3 -c 'import json,sys;print(json.load(sys.stdin)["tag_name"])')"
  echo "scarico runner $VER (linux-arm64)..."
  curl -fsSL -o runner.tgz "https://github.com/actions/runner/releases/download/$VER/actions-runner-linux-arm64-${VER#v}.tar.gz"
  tar xzf runner.tgz && rm runner.tgz
  ./config.sh --url "$REPO_URL" --token "$REG_TOKEN" \
    --labels factory --name factory-1 --unattended --replace
else
  echo "runner già configurato"
fi

# env di factory per i job (il runner non eredita l'env del container)
cd "$DIR"
umask 077
if [ ! -f .env ]; then
  # SPEC 0001: la fonte unica della chiave è il .env del runner. Non si crea un
  # .env dall'env di creazione — la chiave non viaggia più lì, e scriverlo adesso
  # significherebbe riempirlo di valore vuoto.
  echo "ERROR: $DIR/.env non esiste (fonte unica non disponibile)." >&2
  echo "  Dopo ogni ricreazione del container il .env va ripristinato PRIMA di" >&2
  echo "  questo script: Stage 5 golden path, apply/restore-runner-env.sh" >&2
  echo "  (chiavi dal portachiavi via stdin, permessi 600). Nessun runner avviato." >&2
  exit 1
fi
chmod 600 .env

if pgrep -f "$DIR/run.sh" >/dev/null 2>&1; then
  echo "runner già in esecuzione"
else
  # SPEC 0001 b2: fonte unica .env — env di processo corrente a ogni avvio
  set -a; . "$DIR/.env"; set +a
  nohup ./run.sh > runner.stdout.log 2>&1 &
  echo "runner avviato (stdout: $DIR/runner.stdout.log, diag: $DIR/_diag/)"
fi
