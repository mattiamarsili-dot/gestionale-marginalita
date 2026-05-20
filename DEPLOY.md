# Deploy su Render — Guida passo-passo

## Prerequisiti
- Account [GitHub](https://github.com) *(gratuito)*
- Account [Neon](https://neon.tech) *(gratuito — PostgreSQL cloud)*
- Account [Render](https://render.com) *(gratuito — web service)*
- Git installato sul Mac (`git --version` per verificare)

---

## Step 1 — Pubblica il codice su GitHub

Apri il terminale nella cartella del progetto ed esegui:

```bash
cd "/Users/mattiamarsili/Desktop/Progetti Code/Gestionale Marginalità"

git init
git add .
git commit -m "gestionale marginalità v1"
```

Poi vai su [github.com/new](https://github.com/new) e crea un repository **privato** chiamato `gestionale-marginalita`.

Torna nel terminale e collega il repo:

```bash
git remote add origin https://github.com/TUO-USERNAME/gestionale-marginalita.git
git branch -M main
git push -u origin main
```

> **Nota:** il `.gitignore` già esclude `.env`, `*.json` e il database locale — le credenziali non verranno mai caricate su GitHub.

---

## Step 2 — Crea il database PostgreSQL su Neon

1. Vai su [neon.tech](https://neon.tech) → **Create a project**
2. Nome progetto: `gestionale` — Regione: `eu-west-1` (Irlanda, la più vicina)
3. Clicca **Create project**
4. Nella schermata successiva copia la **connection string** nel formato:
   ```
   postgresql://user:password@ep-xxx.eu-west-1.aws.neon.tech/neondb?sslmode=require
   ```
   Salvala — servirà nel prossimo step.

---

## Step 3 — Crea il Web Service su Render

1. Vai su [render.com](https://render.com) → **New → Web Service**
2. Connetti il tuo account GitHub e seleziona il repo `gestionale-marginalita`
3. Render rileva automaticamente `render.yaml` — controlla che i campi siano:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
4. Clicca **Create Web Service** (non ancora Deploy — prima imposta le variabili)

---

## Step 4 — Imposta le variabili d'ambiente

Nella dashboard Render → **Environment** → aggiungi queste variabili:

| Variabile | Valore |
|---|---|
| `DATABASE_URL` | connection string Neon copiata al Step 2 |
| `ACCESS_CODE` | codice scelto per accedere all'app (es. `margini2024`) |
| `SECRET_KEY` | lascia che Render lo generi → tasto **Generate** |
| `DRIVE_FOLDER_ID` | `10s5UQAE24zBARmTJbH3J_YiCkBX9rZWE` |
| `GOOGLE_CREDENTIALS_JSON` | vedi istruzioni sotto |

### Come ottenere GOOGLE_CREDENTIALS_JSON su una riga

Nel terminale Mac:

```bash
python3 -c "
import json
with open('/Users/mattiamarsili/Downloads/progetto-margini-sapio-062dcb97ed3c.json') as f:
    print(json.dumps(json.load(f)))
" | pbcopy
```

Questo comando copia il JSON su una riga negli appunti. Incollalo direttamente nel campo `GOOGLE_CREDENTIALS_JSON` su Render.

---

## Step 5 — Deploy e verifica

1. Dopo aver impostato tutte le variabili, clicca **Manual Deploy → Deploy latest commit**
2. Attendi 2-3 minuti (la prima build scarica le dipendenze)
3. Render mostrerà il log in tempo reale — alla fine apparirà:
   ```
   Your service is live 🎉
   ```
4. Apri l'URL fornito da Render (es. `https://gestionale-marginalita.onrender.com`)
5. Accedi con il codice impostato in `ACCESS_CODE`

> **Al primo avvio** `init_db()` crea automaticamente lo schema su PostgreSQL — nessun intervento manuale necessario.

---

## Variabili riepilogo

| Variabile | Locale (`.env`) | Render |
|---|---|---|
| `ACCESS_CODE` | *(vuoto = nessun login)* | codice scelto |
| `SECRET_KEY` | `dev-only-change-in-prod` | generato da Render |
| `DATABASE_URL` | *(vuoto = SQLite)* | connection string Neon |
| `DRIVE_FOLDER_ID` | `10s5UQAE24zBARmTJbH3J_YiCkBX9rZWE` | stesso valore |
| `GOOGLE_CREDENTIALS_FILE` | percorso file JSON locale | — (non usare su Render) |
| `GOOGLE_CREDENTIALS_JSON` | — (non serve in locale) | JSON su una riga |

---

## Aggiornamenti futuri

Ogni volta che modifichi il codice in locale:

```bash
git add .
git commit -m "descrizione modifica"
git push
```

Render rileva il push e rideploya automaticamente in 1-2 minuti.
