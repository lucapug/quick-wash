#!/bin/sh
# Factory — autostart del runner al boot del container (APPROVATO UTENTE
# 13/11, checkpoint ratificato §12.4; entry fastlane: factory-infra
# docs/fastlane-log.md). Detached e idempotente: NON esegue setup-executors,
# NON tocca il .env (SPEC 0001: fonte unica, un solo file; se il .env manca
# il runner NON parte — Stage 5 richiesto, nessun file creato dal boot).
# Eseuito come ENTRYPOINT nel Dockerfile: avvia il runner in background e
# mantiene il container vivo execando il CMD originale ("$@").
set -u
DIR="$HOME/actions-runner"

if [ -f "$DIR/.runner" ] && [ -f "$DIR/.env" ]; then
  if pgrep -f "$DIR/run.sh" >/dev/null 2>&1; then
    echo "autostart: runner gia' in esecuzione"
  else
    cd "$DIR"
    # SPEC 0001 b2: fonte unica .env — env di processo a ogni avvio
    set -a; . "$DIR/.env"; set +a
    nohup ./run.sh >> "$DIR/runner.stdout.log" 2>&1 &
    echo "autostart: runner avviato al boot"
  fi
else
  echo "autostart: skip — runner non configurato o .env assente (Stage 5)"
fi

if [ $# -eq 0 ]; then
  exec sleep infinity
else
  exec "$@"
fi
