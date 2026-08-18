import os

# Carica .env se presente (sviluppo locale) — ignorato in produzione
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass

# ── Costanti di business ──────────────────────────────────────────────────────
PROVVIGIONE_PCT         = 0.16   # standard base: 16%
PROVVIGIONE_PCT_17      = 0.17   # tier 2: 17% (fatturato ASL annuo > 250.000 €)
PROVVIGIONE_PCT_18      = 0.18   # tier 3: 18% (fatturato ASL annuo > 350.000 €)
PROVVIGIONE_PCT_RIDOTTA = 0.12   # Nemo: 12% (invariato)
STRUTTURA_PCT           = 0.10   # 10% sul totale ricavi (ASL + privato)

SOGLIA_PROV_17  = 250_000.0  # € fatturato ASL annuo → scatta 17%
SOGLIA_PROV_18  = 350_000.0  # € fatturato ASL annuo → scatta 18%

MARGINE_SOGLIA_OK   = 20.0  # % verde
MARGINE_SOGLIA_WARN = 10.0  # % giallo

# ── Centri e ASL (liste "seme" delle tendine) ───────────────────────────────
# Valori di partenza delle tendine "Centro" e "ASL". Le liste mostrate nei form
# sono queste UNITE ai valori già salvati nel DB (vedi opzioni_centri/opzioni_asl
# in app.py): aggiungendo un nuovo centro/ASL e salvando, quel valore ricompare
# nelle selezioni successive. Qui si modificano solo i valori di partenza.
CENTRI = [
    "Santa Lucia",
    "HBG",
    "Nemo",
    "PTV",
    "Campus",
    "Gemelli",
    "Policlinico",
    "ASL",
]

ASL_OPZIONI = [
    "RM1", "RM2", "RM3", "RM4", "RM5", "RM6",
    "FR", "VT", "LT",
]

# ── Stato di lavorazione della pratica (workflow ordinato) ──────────────────
# Avanzamento della pratica. Gli stati sono ORDINATI: lo stato avanza in automatico
# quando si generano i moduli o si conferma l'ordine (vedi ricalcola_stato_pratica
# in app.py), ma resta correggibile a mano dal dropdown. L'ultimo stato "Fatturato"
# coincide con pratiche.fatturata = TRUE e sparisce dalla lista pratiche.
STATI_LAVORAZIONE = ["Da valutare", "Prescritto", "ASL", "Autorizzato", "Ordinato", "Fatturato"]

# Rimappatura dei vecchi stati (prima del workflow automatico) verso i nuovi.
# Usata una tantum in migrate_stati() per non perdere i dati in produzione.
STATI_LAVORAZIONE_LEGACY = {
    "Segnalato": "Da valutare",
    "Valutato":  "Da valutare",
    "ASL":       "ASL",
    "Ordini":    "Ordinato",
    "Consegna":  "Ordinato",
}

# ── Note/Task: priorità e scadenza automatica ────────────────────────────────
NOTE_PRIORITA = ["Media", "Alta", "Urgente"]
# Giorni entro cui il task va gestito, per priorità: definiscono la scadenza/avviso
# calcolata in automatico quando non viene impostata a mano.
NOTE_PRIORITA_GIORNI = {"Media": 14, "Alta": 6, "Urgente": 3}

# ── Tipologia ausilio: valori "seme" dalle codifiche LEA (Nomenclatore protesi,
# classi ISO 9999 dell'assistenza protesica). La lista mostrata nei form è questa
# UNITA ai valori già usati nelle pratiche: ogni nuova tipologia salvata ricompare
# poi nelle selezioni successive (auto-estendibile, come Centri/ASL).
LEA_TIPOLOGIE = [
    "Ortesi spinali (busti/corsetti)",
    "Ortesi per arto superiore",
    "Ortesi per arto inferiore",
    "Ortesi del piede e plantari",
    "Calzature ortopediche",
    "Protesi di arto",
    "Carrozzine e sistemi di postura",
    "Ausili per la deambulazione",
    "Ausili antidecubito",
    "Ausili per stomia e incontinenza",
]

# ── Rinnovi ausili/ortesi: tempi di rinnovo per categoria ─────────────────────
# La scadenza si calcola dalla DATA PRATICA (solo mese/anno) + i mesi qui sotto.
# Regola minori: se il paziente ha < 18 anni alla data pratica, si usano i mesi
# ridotti (RINNOVO_MESI_MINORE). L'età si valuta dalla data di nascita.
RINNOVO_CATEGORIE = {            # chiave interna → etichetta mostrata
    "standard":               "Standard (5 anni)",
    "carrozzina_elettronica": "Carrozzina elettronica (6 anni)",
    "ortesi_superiore":       "Ortesi arto superiore — busto/avambraccio-mano-dita/shoulder (36 mesi)",
    "ortesi_inferiore":       "Ortesi arto inferiore — hip/afo/knee (24 mesi)",
}
RINNOVO_MESI = {                 # adulti (≥ 18 anni)
    "standard":               60,
    "carrozzina_elettronica": 72,
    "ortesi_superiore":       36,
    "ortesi_inferiore":       24,
}
RINNOVO_MESI_MINORE = {          # minorenni (< 18 anni alla data pratica)
    "standard":               24,
    "carrozzina_elettronica": 24,
    "ortesi_superiore":       12,
    "ortesi_inferiore":       12,
}
RINNOVO_MESI_DEFAULT = 60        # fallback se categoria sconosciuta
# Parole chiave (minuscolo) per classificare tipologia/ausilio in una categoria.
# L'ordine conta: la prima categoria che combacia vince.
RINNOVO_KEYWORDS = {
    "carrozzina_elettronica": ["elettronic", "comandi alt"],
    "ortesi_superiore":       ["shoulder", "busto", "spine", "spinal", "avambraccio",
                               "mano", "dita", "hand", "arto superiore"],
    "ortesi_inferiore":       ["hip", "afo", "knee", "arto inferiore", "ginocchio",
                               "anca", "caviglia"],
}

# ── App ───────────────────────────────────────────────────────────────────────
SECRET_KEY    = os.environ.get("SECRET_KEY", "dev-only-change-in-prod")
ACCESS_CODE   = os.environ.get("ACCESS_CODE", "")   # vuoto = nessun login in sviluppo
UPLOAD_FOLDER = "uploads"
MAX_UPLOAD_MB = 20

# ── Estrazione anagrafica da testo (Claude API) ──────────────────────────────
# Chiave API (Anthropic Console, fatturazione a consumo separata dagli abbonamenti).
# Vuota = funzione "Incolla messaggio" disattivata (nessuna chiamata, nessun costo).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

# ── Bot Telegram (apertura rapida, task, avvisi, cambio stato) ────────────────
# Token del bot creato con @BotFather. Vuoto = bot disattivato (nessun webhook).
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
# Secret verificato sull'header del webhook (Telegram lo rimanda a ogni update):
# protegge la route /telegram/webhook da chiamate spoofate.
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
# Token che protegge la route del digest giornaliero (chiamata da UptimeRobot/cron).
TELEGRAM_DIGEST_TOKEN = os.environ.get("TELEGRAM_DIGEST_TOKEN", "")
# URL pubblico dell'app, per i deep-link nei messaggi (es. https://...onrender.com).
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

# ── Database ──────────────────────────────────────────────────────────────────
# Se DATABASE_URL è impostato (produzione) → PostgreSQL, altrimenti → SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SQLITE_PATH  = os.environ.get("SQLITE_PATH", "gestionale.db")

# ── Google Drive ───────────────────────────────────────────────────────────────
# ID della cartella Drive da monitorare (dall'URL della cartella)
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
# Credenziali Service Account: da env var JSON (Render) o da file locale
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
if not GOOGLE_CREDENTIALS_JSON:
    _cred_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "")
    if _cred_file and os.path.isfile(_cred_file):
        with open(_cred_file) as _f:
            GOOGLE_CREDENTIALS_JSON = _f.read()

# ── Google Drive — archiviazione PDF (OAuth utente) ─────────────────────────────
# Credenziali OAuth "App web" create dall'utente in Google Cloud Console.
# Servono per CARICARE i PDF generati nel Drive personale dell'utente, anche in
# cartelle già esistenti di cui si incolla il link nella pratica (scope: drive).
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
# Cartella Drive da cui parte il navigatore quando si sceglie la cartella predefinita
# (comodità: è la cartella "madre" dell'archivio). Override in DB o via env.
DRIVE_BROWSE_ROOT = os.environ.get("DRIVE_BROWSE_ROOT", "19kXde5XNsco4XrfQRVaAvKlcCABEFXUg")

# ── Backup automatico (backup_auto.py) ──────────────────────────────────────────
# Recapito del backup JSON via email (SMTP). Tutte opzionali: se SMTP_HOST o
# BACKUP_EMAIL_TO mancano, l'email viene saltata e resta solo la copia locale.
# Con Gmail: SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, SMTP_USER=la-tua@gmail.com,
# SMTP_PASSWORD = "password per le app" (non la password normale dell'account).
SMTP_HOST         = os.environ.get("SMTP_HOST", "")
SMTP_PORT         = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_USER         = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD     = os.environ.get("SMTP_PASSWORD", "")
BACKUP_EMAIL_TO   = os.environ.get("BACKUP_EMAIL_TO", "")
BACKUP_EMAIL_FROM = os.environ.get("BACKUP_EMAIL_FROM", "") or SMTP_USER
# Copia locale con rotazione: dove salvare e quante copie tenere.
BACKUP_DIR        = os.environ.get("BACKUP_DIR", ".")
BACKUP_KEEP       = int(os.environ.get("BACKUP_KEEP", "8") or "8")
