# Gestionale Marginalità — Stato Avanzamento

## Stack
- **Backend:** Flask 3.0 + Python 3.12
- **DB:** SQLite (locale) / PostgreSQL via Neon (produzione)
- **Frontend:** Bootstrap 5.3 + JS vanilla
- **Deploy target:** Render (web service gratuito)
- **Porta locale:** 5001

---

## Funzionalità implementate

### Core
| Feature | File | Note |
|---|---|---|
| Dashboard mensile con filtro mese | `app.py`, `dashboard.html` | Selector mese, stat card, tabella pratiche |
| Nuova pratica | `app.py`, `nuova_pratica.html` | Form con riepilogo margine live |
| Dettaglio pratica | `app.py`, `dettaglio_pratica.html` | Dati + fornitori + analisi margine |
| **Modifica pratica** | `app.py`, `modifica_pratica.html` | Form precompilato, fornitori editabili |
| Elimina pratica | `app.py`, `dettaglio_pratica.html` | Modal di conferma |

### Calcolo margine
| Regola | Valore | Configurabile in |
|---|---|---|
| Provvigione standard | 16% | `config.py` → `PROVVIGIONE_PCT` |
| **Provvigione ridotta** | **12%** | `config.py` → `PROVVIGIONE_PCT_RIDOTTA` |
| Struttura | 5% | `config.py` → `STRUTTURA_PCT` |
| Soglia OK | ≥ 20% | `config.py` → `MARGINE_SOGLIA_OK` |
| Soglia warning | ≥ 10% | `config.py` → `MARGINE_SOGLIA_WARN` |

Formula: `MOL = Ricavi ASL − Costo Fornitori − Provvigione − Struttura`

Il **% provvigione è scelto per ogni pratica** (radio 16% / 12%) e salvato nel DB.
Il **margine mensile** nel dashboard è calcolato sul totale aggregato (non media delle %), come una singola maxi-pratica.

### PDF extraction (`pdf_extractor.py`)
- Doppio stadio: table extraction → bottom-up text scan
- Normalizzazione formato italiano (1.234,56 → 1234.56)
- Deduplicazione candidati, max 5 risultati, suggerito = il più probabile
- Pulizia automatica file temporanei su Render/Railway

### Autenticazione
- Codice unico condiviso via env var `ACCESS_CODE`
- Se `ACCESS_CODE` è vuoto → accesso libero in sviluppo locale
- `SESSION` permanente, logout esplicito

### Google Drive (`drive_sync.py`)
- Bottone "Sincronizza Drive" nel dashboard (visibile solo se configurato)
- Lista PDF nuovi nella cartella monitorata (esclude già importati)
- Estrazione automatica importo da ogni PDF
- Click "Crea Pratica" → form precompilato con fornitore + importo
- `drive_file_id` salvato in DB per non riproporre file già importati

### Database dual-mode (`database.py`)
- SQLite in sviluppo, PostgreSQL in produzione
- `init_db()` + `migrate_db()` chiamati all'avvio (funziona con gunicorn)
- `_PH` e `_DATE_FILTER` calcolati una volta all'avvio (non per ogni request)
- `last_inserted_id(cur)` astrae `lastrowid` vs `lastval()`

---

## Schema DB

### `pratiche`
| Colonna | Tipo | Note |
|---|---|---|
| `id` | INTEGER / SERIAL | PK autoincrement |
| `nome_paziente` | TEXT | |
| `data_pratica` | DATE | |
| `importo_asl` | REAL | netto IVA |
| `provvigione_pct` | REAL | 0.16 o 0.12, default 0.16 |
| `note` | TEXT | nullable |
| `creato_il` | TIMESTAMP | default NOW() |

### `preventivi`
| Colonna | Tipo | Note |
|---|---|---|
| `id` | INTEGER / SERIAL | PK |
| `pratica_id` | INTEGER | FK → pratiche.id CASCADE |
| `nome_fornitore` | TEXT | |
| `importo` | REAL | netto IVA |
| `file_pdf` | TEXT | path locale, nullable |
| `drive_file_id` | TEXT | ID file Drive, nullable |

---

## File del progetto
```
app.py                  — routes Flask
config.py               — costanti e env var
database.py             — layer DB, calcola_margine, migrate
pdf_extractor.py        — estrazione totale da PDF
drive_sync.py           — integrazione Google Drive
templates/
  base.html             — layout con navbar
  base_public.html      — layout senza navbar (login)
  login.html            — pagina accesso
  dashboard.html        — home con stat e tabella mensile
  nuova_pratica.html    — form inserimento + riepilogo live
  modifica_pratica.html — form modifica pratica esistente
  dettaglio_pratica.html — vista dettaglio + analisi margine
static/style.css        — stili custom
requirements.txt        — dipendenze Python
Procfile                — gunicorn per Render
render.yaml             — config deploy Render
```

---

## Da fare: Deploy

### Step 1 — Git + GitHub
```bash
git init
git add .
git commit -m "gestionale marginalità v1"
# crea repo su GitHub → push
git remote add origin https://github.com/<utente>/<repo>.git
git push -u origin main
```

### Step 2 — Database Neon (PostgreSQL gratuito)
1. Registrati su [neon.tech](https://neon.tech)
2. Crea nuovo progetto → copia la connection string:
   `postgresql://user:password@host/dbname`

### Step 3 — Deploy su Render
1. [render.com](https://render.com) → New Web Service → collega repo GitHub
2. Render rileva `render.yaml` automaticamente
3. Aggiungi env var nella dashboard Render:

| Variabile | Valore |
|---|---|
| `DATABASE_URL` | connection string Neon |
| `ACCESS_CODE` | codice scelto per accedere all'app |
| `SECRET_KEY` | generato da Render (tasto "Generate") |

4. Deploy → al primo avvio `init_db()` crea lo schema su PostgreSQL

### Step 4 — Google Drive (opzionale, dopo il deploy)
1. [Google Cloud Console](https://console.cloud.google.com) → Service Account → scarica JSON
2. Condividi cartella Drive con l'email del service account
3. Aggiungi env var su Render:

| Variabile | Valore |
|---|---|
| `DRIVE_FOLDER_ID` | ID cartella dall'URL Drive |
| `GOOGLE_CREDENTIALS_JSON` | contenuto completo del file `.json` |

---

## Env var riepilogo

| Variabile | Sviluppo locale | Produzione |
|---|---|---|
| `ACCESS_CODE` | *(vuoto = nessun login)* | codice scelto |
| `SECRET_KEY` | `dev-only-change-in-prod` | generato da Render |
| `DATABASE_URL` | *(vuoto = SQLite)* | connection string Neon |
| `SQLITE_PATH` | `gestionale.db` | — |
| `DRIVE_FOLDER_ID` | *(vuoto = Drive disabilitato)* | ID cartella |
| `GOOGLE_CREDENTIALS_JSON` | *(vuoto)* | JSON service account |

---

## Aggiornamento 2026-06-21 — Anagrafica, moduli PDF, mobile, AI, PWA

Tutto deployato in produzione (commit corrente `efb0fcd`). Workflow git: commit su `main` → push (Render auto-deploy) → `git branch -f feat/crm-anagrafica-pdf main` → push.

### Nuove funzionalità
| Feature | File chiave | Note |
|---|---|---|
| Anagrafica clienti strutturata | `database.py` (tabella `clienti`), `cliente_form.html` | CF, nascita, residenza, ASL, centro, medico, documento |
| Pratica a doppia scheda + live | `dettaglio_pratica.html` | codifica ASL/medico, righe ausili, moduli |
| Righe ausili (LEA) | `dettaglio_pratica.html` | Q.tà editabile inline, selezione multipla + elimina, preset |
| Compilazione moduli PDF | `pdf_filler.py` | 8 template; font uniforme 10pt; wrap significato per larghezza reale; **/AP mantenuto** (campi visibili in tutti i viewer) |
| Tutore legale (deleghe) | `clienti.ha_tutore + tutore_*`, `pdf_filler.py` | spunta in anagrafica/mobile; Delega RM2 compila il blocco delegato col documento del tutore |
| Tendine Centro/ASL persistenti | `config.py` (CENTRI, ASL_OPZIONI), `_widgets.html`, `static/select-add.js` | seme ∪ valori DB; "➕ Aggiungi nuovo" |
| Copia ASL+medico in pratica | `app.py` (nuova_pratica, /api/clienti) | da anagrafica alla creazione/selezione |
| Form rapido da tablet | `mobile_nuovo.html`, route `/mobile/nuovo` | input grandi (Scribble), salva cliente + apre pratica |
| Pagina QR | `mobile_qr.html`, route `/mobile` | QR verso il form mobile |
| Estrazione anagrafica da testo (AI) | `ai_extract.py`, route `/api/estrai-cliente` | Claude API (claude-opus-4-8); card "Incolla messaggio" nel form mobile; attiva solo con `ANTHROPIC_API_KEY` |
| Elimina pratica dalla vista Pratiche | `pratiche.html` | cestino per riga (anche fatturate) |
| PWA installabile | route `/manifest.webmanifest`, `/sw.js`, `static/icons/` | "Aggiungi a Home"; SW cache-a solo asset statici |

### Env var aggiunte
| Variabile | Sviluppo | Produzione | Scopo |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | *(vuoto = AI off)* | da console.anthropic.com | estrazione anagrafica da testo (fatturazione API separata dagli abbonamenti) |
| `ANTHROPIC_MODEL` | `claude-opus-4-8` | opzionale | modello estrazione |

### In sospeso / prossimi passi
- Pulire su **produzione (Neon)** i due "Pol. Tor Vergata"/"Pol. TorVergata" → `centro='PTV'` (in locale già fatto; 3 clienti). Da app o SQL.
- Impostare `ANTHROPIC_API_KEY` su Render per attivare l'estrazione AI.
- Migliorie online non ancora fatte: **anti-sleep (UptimeRobot)**, **dominio personalizzato**.
- PDF: mappare il blocco delegato posizionale della **Delega Generica** al tutore (oggi solo RM2).
