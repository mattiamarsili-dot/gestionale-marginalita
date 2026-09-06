# CLAUDE.md — Gestionale Marginalità / CRM Ausili Sanitari

Gestionale web (Flask) per pratiche di ausili sanitari: clienti, preventivi
fornitori, calcolo margine, fatturazione, compilazione moduli PDF/Word.
**In produzione** su Render (DB PostgreSQL su Neon). In locale: SQLite, porta 5001.

> `CRM AM/` è un vecchio prototipo localStorage tenuto solo come riferimento
> (git-ignored). L'app reale è questa.

## Stack
Flask 3 + Python 3.12 · Bootstrap 5.3 + JS vanilla + Jinja2 · `pdfplumber`/pypdf
in ingresso, `pypdf`+`reportlab` in uscita · Google Drive via service account /
OAuth · deploy Render (`Procfile`, `render.yaml`, gunicorn).

## File principali
| File | Scopo |
|---|---|
| `app.py` | tutte le route Flask |
| `config.py` | costanti di business + env var |
| `database.py` | layer DB, schema dual SQLite/Postgres, `calcola_margine`, migrazioni |
| `pdf_filler.py` | compilazione moduli PDF in uscita (`PDF_TEMPLATES`, `build_field_map`, `compila_pdf`) |
| `word_filler.py` | moduli Word (motore "celle" + motore segnaposto `{{chiave}}`) |
| `pdf_extractor.py` | estrazione importo dai PDF fornitori |
| `drive_sync.py` / `drive_archive` | integrazione Google Drive |
| `rinnovi.py` | scadenze rinnovi ausili |
| `assets/pdf-templates/` | PDF compilabili + `pdf_fields.json` (fonte di verità nomi campo) |
| `scripts/dump_pdf_fields.py` | rigenera `pdf_fields.json` |
| `import_fatturati_*.py` + `fatturati_common.py` | import mensile pratiche fatturate (untracked) |

## REGOLA CRITICA — dual-DB (SQLite locale / PostgreSQL prod)
Ogni query deve girare su entrambi i dialetti. In `database.py`:
`_IS_POSTGRES` = `bool(DATABASE_URL)` · `_PH` = placeholder (`%s` / `?`) → **usare
sempre `{_PH}`, mai `?`/`%s` hardcoded** · `_DATE_FILTER`, `_MONTH_FORMAT`,
`_FATTURATA_TRUE` = frammenti SQL precalcolati · `last_inserted_id(cur)`.

**Aggiungere tabella/colonna:**
1. Aggiungila a `_SQLITE_SCHEMA` **e** `_POSTGRES_SCHEMA` (tipi giusti per ciascuno).
2. `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (Postgres) + equivalente try/except
   (SQLite) in `migrate_db()`, **idempotente**.
3. Mai modifiche distruttive: i DB in produzione hanno dati reali.

`init_db()` + `migrate_db()` girano a ogni avvio (anche sotto gunicorn).

## Tabelle
`clienti` (anagrafica: CF, nascita, residenza, ASL, centro, medico, tutore…) ·
`pratiche` (`cliente_id` FK, `importo_asl`, `importo_privato`, `provvigione_pct`,
`fatturata`, `data_fatturazione`, `stato_lavorazione`, `ausilio`, `sign_terapeutico`,
`moduli_attivi`/`moduli_generati`, `drive_archivio_id`…) · `preventivi` (costi
fornitore, `importo` = fonte di verità per margine) · `righe_ausili` (codici ISO
della pratica) · `utenti` (login email+password, ruoli admin/operatore) ·
`preset_ausili`/`preset_righe` · `significato_catalogo` · `note`/`note_assegnatari`
(task multi-utente) · `contatti_clinici` · `rinnovi` · `fornitori_sconti` · `app_config`.

## Logica di business (`config.py`)
| Regola | Valore |
|---|---|
| Provvigione base / tier2 / tier3 | 16% / 17% (ASL annuo >250k) / 18% (>350k) |
| Provvigione ridotta (Nemo) | 12% |
| Struttura | 10% sul totale ricavi (ASL+privato) |
| Soglia margine OK / warn | ≥20% / ≥10% |

`MOL = (ASL + privato) − costo_fornitori − provvigione − struttura`.
Provvigione e struttura sul totale ricavi; la **soglia annua** dello scaglione usa
solo l'ASL fatturato (`provvigione_corrente()`).

## Route (`app.py`)
Pagine: `dashboard` (`/`), `nuova_pratica`, `dettaglio_pratica`, `modifica_pratica`,
`pratiche`, `clienti`, `fatturati`, `rinnovi`, `contatti`, `presets`, `panoramica`
(business, admin-only). POST mirati accettano `torna` per il redirect. API JSON
sotto `/api/…`. Auth: login multiutente in `before_request` (`controlla_accesso`),
seed admin da env `ADMIN_EMAIL/PASSWORD/NOME`.

## Moduli PDF (`pdf_filler.py`)
`PDF_TEMPLATES[id]` ha `categoria` che decide la modificabilità del PDF scaricato:
`prescrizione`→editabile · `delega`/`sapio`→parziale (campi con dato dal DB fissi,
resto a mano) · altri→bloccato. Nomi campo = `assets/pdf-templates/pdf_fields.json`
(rigenerabile con `scripts/dump_pdf_fields.py`). Alcuni template ricostruiti da
`scripts/build_*.py` (reportlab).

## Sviluppo & deploy
- Locale: `python3` (non `python`), venv in `.venv/`, `python3 app.py` → :5001, SQLite.
- Test: niente pytest installato; verifiche via script ad hoc / `app.test_client()`
  con sessione finta (`s['autenticato']=True`).
- Deploy: **push su `main` → Render fa auto-deploy**. Migrazioni al boot.
- Import fatturati su Neon: `DATABASE_URL='postgres://…' python import_fatturati_<mese>.py [--apply]`
  (dry-run di default).
- Service worker (`/sw.js` in `app.py`): asset in **network-first**; su cambio
  strategia bumpare `CACHE` (`gm-vN`).

## Cosa NON fare
- Niente `?`/`%s` hardcoded nelle query — sempre `{_PH}`.
- Non toccare uno schema senza aggiornare **entrambi** + `migrate_db()`.
- Niente modifiche distruttive allo schema (DB prod con dati reali).
- Non committare `CRM AM/`, `.env`, `*.db`, `*.xlsx`/`*.docx` (dati pazienti),
  credenziali Google.
- Non rimettere `*.json` generico nel `.gitignore`: preset e `pdf_fields.json`
  vanno versionati.
- `preventivi.importo` resta l'unica fonte per margine/MOL: non calcolarlo altrove.
