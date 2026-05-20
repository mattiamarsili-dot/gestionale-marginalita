import os

# Carica .env se presente (sviluppo locale) — ignorato in produzione
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass

# ── Costanti di business ──────────────────────────────────────────────────────
PROVVIGIONE_PCT        = 0.16   # standard: 16% sui ricavi ASL
PROVVIGIONE_PCT_RIDOTTA = 0.12  # ridotta:  12% sui ricavi ASL
STRUTTURA_PCT          = 0.05   # 5%  sui ricavi ASL

MARGINE_SOGLIA_OK   = 20.0  # % verde
MARGINE_SOGLIA_WARN = 10.0  # % giallo

# ── App ───────────────────────────────────────────────────────────────────────
SECRET_KEY    = os.environ.get("SECRET_KEY", "dev-only-change-in-prod")
ACCESS_CODE   = os.environ.get("ACCESS_CODE", "")   # vuoto = nessun login in sviluppo
UPLOAD_FOLDER = "uploads"
MAX_UPLOAD_MB = 20

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
