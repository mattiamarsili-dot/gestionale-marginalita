# CLAUDE.md — Gestionale Marginalità / CRM Ausili Sanitari

Questo file orienta Claude Code (e qualsiasi agente AI) prima di toccare il codice.
Leggerlo interamente prima di fare modifiche.

> ⚠️ Da non confondere con `CRM AM/CLAUDE.md`: quello descrive un **vecchio prototipo
> localStorage** (HTML+JS vanilla) tenuto **solo come riferimento**. L'app reale è questa,
> in Flask. La cartella `CRM AM/` è materiale di riferimento ed è git-ignored.

---

## Cos'è questo progetto

Gestionale web per la gestione di **pratiche di ausili sanitari**: pazienti/clienti,
preventivi fornitori, calcolo del margine, fatturazione e (in arrivo) compilazione
automatica di moduli PDF.

**Stato:** in produzione. Deployato su Render con DB PostgreSQL su Neon.
In sviluppo locale gira su SQLite, porta 5001.

**In corso (branch `feat/crm-anagrafica-pdf`):** consolidamento delle funzioni del vecchio
prototipo dentro questo Flask — anagrafica clienti strutturata e compilazione moduli PDF.
Vedi sezione "Roadmap di consolidamento" in fondo.

---

## Stack

- **Backend:** Flask 3 + Python 3.12
- **DB:** SQLite (locale) / PostgreSQL via Neon (produzione) — vedi pattern dual-DB sotto
- **Frontend:** Bootstrap 5.3 + JS vanilla, template Jinja2
- **PDF in (estrazione):** `pdfplumber`/pypdf in `pdf_extractor.py`
- **PDF out (compilazione):** `pypdf` in `pdf_filler.py` (in costruzione)
- **Drive:** Service Account Google in `drive_sync.py`
- **Deploy:** Render (`Procfile`, `render.yaml`, gunicorn)

---

## Mappa dei file

| File | Scopo |
|---|---|
| `app.py` | Tutte le route Flask (~610 righe) |
| `config.py` | Costanti di business (provvigioni, soglie) + env var |
| `database.py` | Layer DB, schema dual SQLite/Postgres, `calcola_margine`, migrazioni |
| `pdf_extractor.py` | Estrazione importo totale dai PDF fornitori (PDF in entrata) |
| `pdf_filler.py` | Compilazione moduli PDF (PDF in uscita) — **in costruzione** |
| `drive_sync.py` | Integrazione Google Drive |
| `scripts/dump_pdf_fields.py` | Estrae i nomi campo AcroForm dei template → `pdf_fields.json` |
| `templates/*.html` | Viste Jinja2 (base, dashboard, pratica, fatturati, login) |
| `assets/pdf-templates/` | PDF template compilabili + `pdf_fields.json` (field-map reale) |
| `static/style.css` | Stili custom |
| `CRM AM/` | **Riferimento** — vecchio prototipo + documentazione (git-ignored) |

---

## Pattern dual-DB (SQLite / PostgreSQL) — REGOLA CRITICA

Tutto il codice DB deve funzionare su entrambi i dialetti. In `database.py`:

- `_IS_POSTGRES` = `bool(DATABASE_URL)` — decide il dialetto all'avvio
- `_PH` = placeholder parametri: `%s` (Postgres) o `?` (SQLite). **Usare sempre `{_PH}`**, mai `?`/`%s` hardcoded.
- `_DATE_FILTER`, `_MONTH_FORMAT`, `_FATTURATA_TRUE` = frammenti SQL precalcolati per i due dialetti
- `last_inserted_id(cur)` astrae `lastrowid` (SQLite) vs `lastval()` (Postgres)

**Quando aggiungi una tabella o colonna:**
1. Aggiungila a `_SQLITE_SCHEMA` **e** `_POSTGRES_SCHEMA` (tipi corretti per ciascuno).
2. Aggiungi un `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (Postgres) e l'equivalente
   try/except (SQLite) in `migrate_db()` — deve essere **idempotente**.
3. Non cambiare colonne esistenti in modo distruttivo: i DB in produzione hanno dati.

`init_db()` + `migrate_db()` girano a ogni avvio (anche sotto gunicorn).

---

## Schema DB attuale

### `pratiche`
`id`, `nome_paziente` (TEXT, oggi testo libero), `data_pratica` (DATE),
`importo_asl` (REAL), `importo_privato` (REAL, default 0), `provvigione_pct` (REAL, default 0.16),
`note`, `fatturata` (BOOL/INT), `data_fatturazione` (DATE), `creato_il` (TIMESTAMP).

### `preventivi`
`id`, `pratica_id` (FK → pratiche CASCADE), `nome_fornitore`, `importo` (REAL),
`file_pdf` (path locale), `drive_file_id`.

> Nota: **non esiste ancora una tabella `clienti`** — `pratiche.nome_paziente` è testo libero.
> Crearla è il primo passo della roadmap (serve a popolare i moduli PDF con CF, indirizzo, ASL…).

---

## Logica di business (config.py)

| Regola | Valore | Costante |
|---|---|---|
| Provvigione base | 16% | `PROVVIGIONE_PCT` |
| Provvigione tier 2 | 17% (fatt. ASL annuo > 250k) | `PROVVIGIONE_PCT_17` / `SOGLIA_PROV_17` |
| Provvigione tier 3 | 18% (fatt. ASL annuo > 350k) | `PROVVIGIONE_PCT_18` / `SOGLIA_PROV_18` |
| Provvigione ridotta (Nemo) | 12% | `PROVVIGIONE_PCT_RIDOTTA` |
| Struttura | 5% sul totale ricavi | `STRUTTURA_PCT` |
| Soglia margine OK / warning | ≥20% / ≥10% | `MARGINE_SOGLIA_OK` / `_WARN` |

`MOL = (ASL + privato) − costo_fornitori − provvigione − struttura`.
Provvigione e struttura si calcolano sul totale ricavi (ASL+privato); la **soglia annua**
per lo scaglione provvigione usa solo l'ASL fatturato (vedi `provvigione_corrente()`).

---

## Convenzioni route (app.py)

- Pagine: `dashboard` (`/`), `nuova_pratica`, `dettaglio_pratica`, `modifica_pratica`, `fatturati`
- Azioni POST mirate: `/pratica/<id>/fattura`, `/data-ordine`, `/data-fattura`, `/importo-privato`,
  `/fornitore/aggiungi`, `/preventivo/<id>/elimina`, `/pratica/<id>/elimina`
- API JSON: `/api/estrai-pdf`, `/api/sync-drive`, `/api/calcola-margine`, `/api/config`
- Le azioni POST accettano un campo `torna` per il redirect di ritorno.
- Auth: `ACCESS_CODE` vuoto = nessun login (sviluppo). `controlla_accesso()` in `before_request`.

---

## Template PDF e field-map

I PDF compilabili sono in `assets/pdf-templates/`. Tutti e 8 hanno campi AcroForm
(verificato con pypdf — la doc `CRM AM/PDF_FIELD_MAP.md` è obsoleta, non fidarsi).

**Fonte di verità per i nomi campo:** `assets/pdf-templates/pdf_fields.json`,
rigenerabile con `python scripts/dump_pdf_fields.py`.

| File | Campi testo | Pagine |
|---|---|---|
| `preventivo-sapio-v1.pdf` | 93 | 1 |
| `Preventivo.pdf` | 93 | 1 |
| `Prescrizione Gen.pdf` | 61 | 2 |
| `Prescrizione HBG.pdf` | 56 | 1 |
| `PrescrizioneSanta lucia.pdf` | 51 | 2 |
| `autocert-asl-rm3.pdf` | 23 | 2 |
| `Delega Generica.pdf` | 40 | 2 |
| `Delega RM2.pdf` | 18 | 2 |

---

## Roadmap di consolidamento (priorità: moduli PDF + anagrafica)

1. **Fase 1 — Anagrafica clienti:** tabella `clienti` (con CF, nascita, residenza, ASL, medico…),
   `pratiche.cliente_id` FK, migrazione dei `nome_paziente` esistenti, route/template anagrafica,
   selettore cliente in `nuova_pratica`.
2. **Fase 2 — Compilazione PDF:** `pdf_filler.py` (`PDF_TEMPLATES`, `build_field_map`, `compila_pdf`
   con pypdf), route `/pratica/<id>/modulo/<template_id>`, bottoni "Genera modulo".
3. **Fase 3 — Preset LEA / ausili:** righe ausili sulla pratica + preset terapeutici
   (dati reali in `CRM AM/therapeutic_presets_seed.json`).
4. **Fase 4 — Automazioni:** archivio Drive per cliente, ricerche, backup schedulato.

---

## Cosa NON fare

- Non usare `?` o `%s` hardcoded nelle query — sempre `{_PH}`.
- Non aggiungere tabelle/colonne senza aggiornare **entrambi** gli schemi e `migrate_db()`.
- Non committare `CRM AM/`, `.env`, `*.db`, file di credenziali Google (già in `.gitignore`).
- Non cambiare in modo distruttivo lo schema: i DB in produzione hanno dati reali.
- Non reintrodurre `*.json` generico nel `.gitignore`: i preset e `pdf_fields.json` vanno versionati.
