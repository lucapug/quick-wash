# ESITO — gara probation quick-wash (opencode vs qwen-code)

- Repo: lucapug/quick-wash-probation (privato, mai flip) — 09/11/2026
- Modalita: dispatch parallelo, stesso container, prompt canonico byte-identico
  (sha256 05b9285bed7e), timebox 2h, deliverable issue-only.
- Punte: entrambe qwen3.8-flash-next-iq2_xs via Strata (variabile harness isolata).

## Dati per lead

| Criterio | qwen-code | opencode |
|---|---|---|
| 1. Copertura R1-R11 + shape tasks + patch addendum | completa (19/28 issue toccano R; shape tutte, incl. tracker evidence) | completa (23/25 issue toccano R; shape tutte) |
| 2. AC misurabili (numeri pack 10/30, 5/24, 14/16/19) | presenti, nessuna vaghezza | presenti, nessuna vaghezza |
| 3. Test nell'issue, info-string = path repo-relative | 23/28, STRICT-compliant (la info-string INIZIA col path) | 22/25, path dopo il language (`python tests/...`): non strict |
| 4. Granularita atomic/complex | 8 atomic / 20 complex | 16 atomic / 9 complex (piu fine per one-in-flight) |
| 5. Ordinamento | sequenza dichiarata su #3 con dipendenze; swap #16 motivato | sequenza dichiarata su #33, 33-57 lineare |
| 6. Fedelta al pack (OTP in-app, buffer 10/30, no deploy + steps doc, catena locale) | decisioni registrate (28 `Decision:`) | decisioni registrate (25 `Decision:`) |
| 7. Igiene (inglese, no path host, no segreti) | ok, no segreti reali, no vaghezze | ok, no segreti reali, no vaghezze |
| Wall-clock | 44 min (17:22-18:06 UTC) | 50 min |
| Issue verificate nel tracker | 28/28 | 25/25 |

Deviazioni: qwen ha usato la GitHub REST API invece del CLI gh (non vietato);
opencode autoreporto impreciso su una "issue #30 con label errata corretta"
(#30 appartiene al set qwen). Entrambi: nessun PR, nessun codice.

## Incidenti

1. Attempt 1: dispatchato il testo canonico "Lancio scaffold" invece del prompt
   dei lead (deviazione ssh minisforum imputabile al testo errato, non addebitata
   ai lead); rerun attempt 2 con prompt canonico verificato byte-identico.
2. Pipeline riattivatasi durante la gara: run su issue di qwen (comments di
   routing su #4-#9, PR spurie #31/#32/#58, causa riattivazione non determinata).
   Run pendenti cancellati, workflow ri-disabilitati, comments eliminati, PR chiuse:
   artefatti esclusi dagli esiti misurati.

## Verdetto (firma utente pendente)

Qualita sostanziale pari su 5/7 criteri; qwen-code vince il criterio 3
(info-string strict, requisito del prompt + tamper-check pipeline) e il
tie-break di rapidita (44 vs 50 min). opencode e piu fine sul sizing.
Raccomandazione: **qwen-code**, in attesa della firma.

## Mappa di trasferimento (da compilare dopo la firma)

Backlog vincitore -> quick-wash: numeri nuovi, label lead:* rimossa,
atomic/complex conservate.


## Verifica post-mitigazione token (verify-after-mutate)

- Gate 1: workflow riabilitati con auth utente gh del Mac -> active x4; nessuna
  approvazione richiesta.
- Gate 2: chiuso come **vettore rimosso**, non ridotto. Il `.gh_token` del
  container (41 byte) era il token OAuth `gho_` dell'utente (prefix verificato),
  con scope `workflow`: PUT enable rispondeva 204. File rimosso dal container
  (il container non ha piu alcuna credenziale); upstream non ruotato perche e
  l'auth operativa del Mac. Per il progetto reale: token dedicato fine-grained
  (Issues RW + PRs Read) creato ex novo.
- Gate 3: catena verde su issue #59 (label atomic, no lead): route 0.95 ->
  pi (pytest pass) -> review APPROVED con tamper-check pass (glm-z1-9b-0414)
  -> factory-merge success -> #59 closed 2026-11-09T20:59:24Z. Runs:
  42697657205 / 42697660078 / 42698053286 / 42698140553. PR #60, merge
  commit 47392c52.
- Gate 4: workflow lasciati active x4 dopo il merge.

## Verdetto (firmato)

Vincitore: **qwen-code** — conferma e firma dell'utente registrata il 10/11/2026.
Il verdetto nasce dal confronto programmatico sui 7 criteri, poi firmato.

## Mappa trasferimento backlog vincitore -> quick-wash (2026-11-10)

Trasferimento via `gh issue create` dal Mac; titoli/body byte-identici verificati 28/28
(source di verità = quick-wash-probation). Label: solo atomic/complex, nessuna lead.

| Source (quick-wash-probation) | Target (quick-wash) | Titolo | Label |
|---|---|---|---|
| #3 | #1 | [atomic] Establish the project context files README and AGENTS.md | atomic |
| #4 | #2 | [atomic] Write the agent-team specification | atomic |
| #5 | #3 | [atomic] Define the tracker conventions for one-issue-in-flight | atomic |
| #6 | #4 | [complex] Stand up the single test seam and the shared fixtures | complex |
| #7 | #5 | [complex] Implement the seed configuration and the domain model | complex |
| #8 | #6 | [complex] Implement the machine state machine and reject invalid transitions (R6) | complex |
| #9 | #7 | [complex] Implement valid start times for real cycle durations (R1, R2) | complex |
| #10 | #8 | [complex] Expose public availability per type with refusal reasons | complex |
| #11 | #9 | [complex] Implement email and in-app OTP sign-in | complex |
| #12 | #10 | [complex] Enforce entitlements on bookings, fault reports and the owner panel | complex |
| #13 | #11 | [complex] Implement booking creation with race-protected assignment (R5) | complex |
| #14 | #12 | [complex] Implement the numeric unlock code and the grace window (R3) | complex |
| #15 | #13 | [complex] Implement device reports and the idle_open event | complex |
| #16 | #14 | [complex] Implement the turnover and cleaning buffers (R10) | complex |
| #17 | #15 | [atomic] Implement the cancellation window (R4) | atomic |
| #18 | #16 | [atomic] Implement the constrained fault report and maintenance (R7) | atomic |
| #19 | #17 | [complex] Implement reassignment with new code and notification (R8) | complex |
| #20 | #18 | [complex] Implement the no-show counter and the booking block (R9) | complex |
| #21 | #19 | [atomic] Implement the per-customer daily booking limit (R11) | atomic |
| #22 | #20 | [complex] Build the customer frontend in Italian | complex |
| #23 | #21 | [complex] Build the minimal owner panel | complex |
| #24 | #22 | [atomic] Add the deterministic fault trigger and the eight-machine demo seed | atomic |
| #25 | #23 | [complex] Instrument the booking journey end to end | complex |
| #26 | #24 | [complex] Alert on customer impact | complex |
| #27 | #25 | [complex] Implement the domain-level on-call responder | complex |
| #28 | #26 | [complex] Containerize the whole system for one-command start | complex |
| #29 | #27 | [complex] Add CI tier 1 on every pull request on the factory-1 runner | complex |
| #30 | #28 | [atomic] Document the deployment steps | atomic |
