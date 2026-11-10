# Bootstrap della factory in un nuovo progetto

Il postCreate ha già installato gli esecutori (opencode, pi, prime-agent) e copiato
`.github/` (workflow `factory-pilot` + script), `pytest.ini` e `opencode.json` nella
root del progetto. **Committa questi file** come primo atto del progetto, poi completa:

## 0. FACTORY_TOKEN (per la pipeline V2 event-driven)

La catena V2 (route → pi → review → merge, con ri-accodazione automatica dopo
CHANGES_REQUESTED) richiede un PAT fine-grained, perché gli eventi generati dal
GITHUB_TOKEN di default non ri-triggerano i workflow:

1. GitHub → Settings → Developer settings → Fine-grained tokens → Generate:
   - Resource owner: il proprio account; Repository access: **solo questo repo**
   - Expiration: 90 giorni (promemoria di rinnovo)
   - Permission: **Contents RW, Issues RW, Pull requests RW, Actions RW,
     Commit statuses RW** (+ Metadata R, automatica). Nota: "Commit statuses"
     è una voce SEPARATA — senza, il check della review fallisce (non fatale).
2. `gh secret set FACTORY_TOKEN --repo <owner>/<repo>` (incolla il token).

## 1. Label di routing (una tantum)

```
gh label create atomic --force
gh label create complex --force
gh label create review:approved --force
gh label create review:changes-requested --force
gh label create review:needs-human --force
```

## 2. Setting di repo: le Actions possono creare PR (una tantum)

```
gh api -X PUT repos/<owner>/<repo>/actions/permissions/workflow \
  -F default_workflow_permissions=write -F can_approve_pull_request_reviews=true
```

## 3. Ripristino `.env` del runner, poi runner self-hosted

Il `.env` dei job NON esiste in una istanza nuova, e `setup-runner.sh` esce con
errore esplicito se manca (single-source SPEC 0001: la chiave non viaggia né nel
template né nell'env di creazione del container). Al PRIMO avvio il postCreate ha
già copiato i file pipeline (copia secret-free, eseguita prima del check della
chiave) ed esce con errore esplicito sul check: comportamento atteso. Dal Mac, col
container app avviato: ripristina il `.env`, poi riesegui `setup-executors.sh` nel
container (idempotente, `cp -n`) per config + probe, e committa i file pipeline
come primo atto dentro il progetto:

```
~/factory-infra/apply/restore-runner-env.sh --container <container-app>
```

(chiavi STRATA/REVIEWER dal portachiavi via stdin, mai argv/log; scrive
`~/actions-runner/.env` con permessi 600). Poi registra il runner:

```
RT=$(gh api -X POST repos/<owner>/<repo>/actions/runners/registration-token --jq .token)
docker exec -e REG_TOKEN="$RT" <container-app> sh .devcontainer/scripts/setup-runner.sh
```

Verifica: `gh api repos/<owner>/<repo>/actions/runners` → runner `factory-1` online.

## 4. Prima issue di prova

Apri una issue con acceptance criteria espliciti (la pipeline classifica
atomic/complex da sola; override col prefisso `[atomic]`/`[complex]` nel titolo).
Catena V2 completa: label routing → pi implementa → PR → review con gate pytest
→ APPROVED: merge automatico e issue chiusa | CHANGES_REQUESTED: ri-accodazione
automatica a pi col feedback nel prompt (max 3, poi `review:needs-human`).

## 5. Dopo un riavvio della macchina host

Il runner vive nel container: il container torna da solo al riavvio del motore
(compose `restart: unless-stopped`), ma il processo runner (nohup) no — se la
factory non prende jobs, verificare il container e rilanciare `setup-runner.sh`
(idempotente). Sul Mac del laboratorio il LaunchAgent
`com.lucapug.factory-bootstrap` rialza OrbStack → container → runner SOLO per
il container del lab: per gli altri progetti scaffoldati il rialzo post-reboot
è per ora manuale (gap noto, in valutazione dalla pre-partita dell'8/11).

## Note operative

- Reviewer indipendente: `scripts/reviewer_call.sh` chiama il **reviewer
  residente GLM-Z1-9B-0414** (Z.ai, reasoning) sul Minisforum, porta 8081 bind
  tailnet (`REVIEWER_BASE_URL` + `REVIEWER_API_KEY` nel `.env` del runner,
  ripristinati al §3). Il residente è un servizio Windows NSSM sempre attivo
  dal 06/11 (boot-start, sessione 0, self-heal) — niente finestre da aprire.
  Residente muto o risposta incompleta (content vuoto, budget token esaurito
  nel reasoning) = verdetto `NEEDS_HUMAN` (label `review:needs-human`): NON
  esiste fallback su pi, sarebbe lo stesso modello dell'autore — autore ≠
  revisore è garantito per costruzione (lezione ciclo #18). Il commento di
  review dichiara sempre il reviewer usato. La ACL del gate per :8081 è già
  nel template.
- I test forniti nell'issue vanno incollati come fenced block con il percorso
  repo nell'info string (es. ` ```python tests/test_x.py `): il workflow
  `pi-review` verifica lo sha256 (`scripts/verify_tests.py`) e un file
  mancante o modificato blocca il merge a prescindere dal verdetto.
- Il router chiama Strata via gate; se il gate è appena stato riavviato, i retry
  con backoff (in `classify.py`) assorbono i 502 transitori.
- CHANGES_REQUESTED senza verdict valido = default sicuro (mai rubber-stamp).
- Il worker è pi (Alibaba): implementa; la review è indipendente per vendor e
  modello (reviewer Z1, Z.ai). `pi-review` accetta anche `workflow_dispatch`
  con input `pr_number` per ri-revieware manualmente una PR già aperta (il
  trigger pull_request non ri-scatta).
- Il runner usa le env di factory dal proprio file `.env` (ripristinato da
  `restore-runner-env.sh`, §3 — golden path Stage 5; `setup-runner.sh` lo
  sourcia con `set -a` e fallisce esplicitamente se manca).
