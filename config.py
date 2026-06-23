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
STRUTTURA_PCT           = 0.05   # 5% sul totale ricavi (ASL + privato)

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
# Avanzamento della pratica, indipendente dalla fatturazione.
STATI_LAVORAZIONE = ["Segnalato", "Valutato", "ASL", "Ordini", "Consegna"]

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
