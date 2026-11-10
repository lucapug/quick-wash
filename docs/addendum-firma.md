# SPEC 0004 — quick-wash: addendum di firma all'audit della prova del fuoco

> La spec di progetto è `C:\Users\lucap\Coding\specs\quick-wash\spec.md` sul
> Minisforum (autore: architetto IQ3_XXS). **spec.md non viene ritoccata**
> (nessun secondo giro architetto): questo addendum è il layer di correzione
> autoritativo e viaggia **insieme a spec.md nel pack** consegnato al lead
> (scaffold/probation: qwen-code vs opencode). Chi splitta i task o reviewa
> le PR lavora contro spec.md + addendum. I path host (Minisforum e questo
> repo) NON sono raggiungibili dagli agenti isolati nel container: allo
> scaffold il pack va **materializzato dentro la cartella di progetto** —
> `spec.md` + `addendum-firma.md` (questo file, copia identica) — e il
> AGENTS.md di progetto deve puntarli come layer spec autoritativo.

- **Stato**: audit GO-con-note (ZCode, 09/11/2026) → **firmata dall'utente 09/11/2026**
- **Autore addendum**: ZCode (auditor, protocollo di audit della prova del
  fuoco: GO / GO-con-note / RISUBMIT) ·
  **Destinatari**: lead in probation, reviewer Z1, utente
- **Rubric**: DataTalksClub AI Dev Tools Zoomcamp 2026 (12 criteri, 24 punti,
  pass 10 — README e `Rubric_aidevtools2026.html` in cartella identici)

## Patch firmate

1. **OTP delivery** — il codice OTP si mostra in-app subito dopo la richiesta
   di sign-in (demo mode). Nessun trasporto email/SMS (già Out of Scope) e il
   no-credential-in-telemetry vieta di loggarlo: US18 si implementa così.
2. **R10, buffer numerati** — turnover buffer **10 minuti**, cleaning buffer
   **30 minuti**, in seed/config come tariffa e orari. Turnover = pausa
   automatica post-`finished` in cui la macchina non è assegnabile; cleaning =
   finestra di `cleaning_required` dopo segnalazione cliente, poi `available`.
   Se un cliente riprova, il ciclo segnala→`cleaning_required` si ripete (US35).
3. **Deployment e CD in Out of Scope** — niente URL pubblico né CD: nessuna
   risorsa free disponibile; secondo progetto sottomesso (il primo ha già
   deployment pubblico e buona peer review). Compensi in scope: **deployment
   steps descritti nella doc** (tier 1 del criterio Deployment = 1 pt) e
   **CI tier-1** (GitHub Actions sul runner self-hosted factory-1, test su
   ogni PR, 1 pt — gratis: nessun minuto Actions consumato, privato o pubblico).
4. **Aritmetica rubrica corretta** — la catena osservabilità+alert+on-call vale
   **5/24** (2+1+2), non 3 come scritto in spec.md. Col deployment fuori:
   **tetto realistico 19/24**, base 16 senza catena, **target utente 14**,
   pass 10. La documentazione di progetto usa questi numeri.
5. **Decisioni aperte 1–3 accettate alla firma** (raccomandazioni architetto):
   fault deterministico (trigger config/owner panel, US61); alert su impatto
   cliente (codice non riscattabile per controller che non risponde, o
   `idle_open`); on-call responder dominio-level (mette in `maintenance`,
   trigghera R8, registra incidente, scala all'owner se nessuna macchina
   libera; niente PR-scrivente). Tutto gira **in locale in compose** — nessuna
   risorsa cloud.
6. **Documentazione home factory** (contenuto di Agent Team Specification +
   Context Management): narrazione del misto **audit su modello di frontiera**
   (cloud endpoint, ZCode) **+ inferenza locale** (intera catena factory:
   brainstorm/spec architetto IQ3_XXS, probation lead qwen-code vs opencode,
   reviewer Z1/3070; processo una-issue-in-volo, autore≠revisore, protocollo
   GO / GO-con-note / RISUBMIT). AGENTS.md punta alle doc modulari.

## Calendario

| Data | Cosa |
|---|---|
| subito (raccomandato 10–11/11) | scaffold repo `--private` (gate pack: copia docs/spec.md + docs/addendum-firma.md prima del commit iniziale) |
| 13/11 | checkpoint go/no-go catena alert+on-call: non dimostrabile → freeze su base 16 |
| 16/11, prima di registrare | flip repo a `public` (abitudine utente: privato durante lo sviluppo) + verifica tracker pubblico ed evidenza agenti visibile |
| 16/11 | sottomissione — fine giornata, Rome (UTC+2) |
| ≤ 21/11 | peer review di 3 progetti (assegnati dopo la chiusura della sottomissione) |

## Note operative

- **Materializzazione in container**: allo scaffold, copiare `spec.md` e
  `addendum-firma.md` dentro la cartella di progetto isolata nel container —
  gli agenti del team non possono leggere i path host esterni (Minisforum,
  factory-infra sul Mac). I task non referenziano mai path host: referenziano
  i file dentro il repo progetto. Per il passaggio umano al minisforum,
  copia del pack anche in `C:\Users\lucap\Coding\specs\quick-wash\`.
- Le 6 pt di scrittura (tracker pubblico+evidenza agenti, AGENTS.md+doc
  modulari, team spec) sono i primi task post-scaffold; le patch entrano nei
  task già numerate (OTP in-app, buffer 10/30, deployment steps, CI tier-1).
- L'evidenza "agents used the tracker" esce dal flusso una-issue-in-volo con
  riferimenti issue nei commit/PR.
- Il reviewer Z1 valuta le PR contro spec.md **+ addendum** (in particolare
  patch 2, 3, 5).
