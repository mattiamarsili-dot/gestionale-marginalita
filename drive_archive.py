"""
Archiviazione dei PDF generati nel Google Drive PERSONALE dell'utente, via OAuth.

A differenza di drive_sync.py (service account, sola lettura, importa i PDF dei
fornitori), qui l'app agisce COME L'UTENTE per CARICARE i moduli generati nelle
sue cartelle. Scope: drive.file → l'app vede/gestisce solo i file e le cartelle
che crea lei (non tocca il resto del Drive).

Setup (una tantum, lato utente):
  1. Google Cloud Console → abilita "Google Drive API".
  2. Schermata consenso OAuth (Esterno) → aggiungi la tua email come utente di test.
  3. Credenziali → ID client OAuth → App web → redirect: <APP>/drive/callback
  4. Metti GOOGLE_OAUTH_CLIENT_ID e GOOGLE_OAUTH_CLIENT_SECRET nelle env.
Poi nel gestionale: Pratiche → box "Archiviazione Drive" → Collega.

Il refresh token e la cartella radice scelta sono salvati in app_config (DB).
"""
import io
import json
import urllib.parse
import urllib.request

from config import GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
from database import config_get, config_set

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    _LIBS = True
except ImportError:
    _LIBS = False

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
_FOLDER_MIME = "application/vnd.google-apps.folder"

# Chiavi in app_config
_K_TOKEN = "drive_refresh_token"
_K_EMAIL = "drive_account_email"
_K_ROOT = "drive_root_folder_id"
_K_ROOT_NAME = "drive_root_folder_name"


# ── Stato ─────────────────────────────────────────────────────────────────────

def configurato() -> bool:
    """True se ci sono le credenziali OAuth (client id/secret)."""
    return _LIBS and bool(GOOGLE_OAUTH_CLIENT_ID) and bool(GOOGLE_OAUTH_CLIENT_SECRET)


def collegato() -> bool:
    """True se l'utente ha già autorizzato (abbiamo un refresh token)."""
    return configurato() and bool(config_get(_K_TOKEN))


def account_email() -> str:
    return config_get(_K_EMAIL, "") or ""


def radice() -> tuple[str, str]:
    """(folder_id, nome) della cartella radice scelta, ('','') se non scelta."""
    return (config_get(_K_ROOT, "") or "", config_get(_K_ROOT_NAME, "") or "")


def imposta_radice(folder_id: str, nome: str):
    config_set(_K_ROOT, folder_id or None)
    config_set(_K_ROOT_NAME, nome or None)


def scollega():
    for k in (_K_TOKEN, _K_EMAIL, _K_ROOT, _K_ROOT_NAME):
        config_set(k, None)


# ── OAuth ─────────────────────────────────────────────────────────────────────

def auth_url(redirect_uri: str, state: str) -> str:
    params = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(_SCOPES),
        "access_type": "offline",       # serve per ottenere il refresh token
        "prompt": "consent",            # forza il refresh token anche su ri-autorizzazione
        "include_granted_scopes": "true",
        "state": state,
    }
    return _AUTH_URI + "?" + urllib.parse.urlencode(params)


def scambia_codice(code: str, redirect_uri: str):
    """Scambia il codice di autorizzazione con i token e salva il refresh token."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(_TOKEN_URI, data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        tok = json.load(r)
    refresh = tok.get("refresh_token")
    if not refresh:
        raise RuntimeError("Google non ha restituito un refresh token. Riprova "
                           "revocando l'accesso precedente (prompt=consent).")
    config_set(_K_TOKEN, refresh)
    # email dell'account (best-effort, per mostrare "Collegato come …")
    try:
        info = _service().about().get(fields="user(emailAddress)").execute()
        config_set(_K_EMAIL, info.get("user", {}).get("emailAddress", ""))
    except Exception:
        pass


def _credentials():
    refresh = config_get(_K_TOKEN)
    if not refresh:
        raise RuntimeError("Google Drive non collegato.")
    creds = Credentials(
        token=None,
        refresh_token=refresh,
        token_uri=_TOKEN_URI,
        client_id=GOOGLE_OAUTH_CLIENT_ID,
        client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=_SCOPES,
    )
    creds.refresh(Request())
    return creds


def _service():
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


# ── Cartelle e upload ─────────────────────────────────────────────────────────

def lista_cartelle(parent: str = None) -> list[dict]:
    """Cartelle gestite dall'app (con drive.file solo quelle create da lei)."""
    svc = _service()
    q = f"mimeType='{_FOLDER_MIME}' and trashed=false"
    if parent:
        q += f" and '{parent}' in parents"
    res = svc.files().list(
        q=q, spaces="drive", fields="files(id, name)", orderBy="name", pageSize=100
    ).execute()
    return res.get("files", [])


def crea_cartella(nome: str, parent: str = None) -> dict:
    svc = _service()
    body = {"name": nome, "mimeType": _FOLDER_MIME}
    if parent:
        body["parents"] = [parent]
    f = svc.files().create(body=body, fields="id, name").execute()
    return {"id": f["id"], "name": f["name"]}


def _trova_cartella(nome: str, parent: str):
    svc = _service()
    safe = nome.replace("'", "\\'")
    q = (f"mimeType='{_FOLDER_MIME}' and trashed=false and name='{safe}'"
         f" and '{parent}' in parents")
    res = svc.files().list(q=q, spaces="drive", fields="files(id, name)", pageSize=1).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def sottocartella_paziente(cliente: dict, root_id: str) -> str:
    """Trova o crea, dentro `root_id`, la sottocartella del paziente. Ritorna l'id."""
    cog = (cliente.get("cognome") or "").strip()
    nome = (cliente.get("nome") or "").strip()
    etichetta = (f"{cog} {nome}").strip() or "Senza nome"
    cf = (cliente.get("codice_fiscale") or "").strip()
    if cf:
        etichetta = f"{etichetta} - {cf}"
    esistente = _trova_cartella(etichetta, root_id)
    if esistente:
        return esistente
    return crea_cartella(etichetta, root_id)["id"]


def carica_pdf(data: bytes, nome: str, folder_id: str) -> dict:
    """Carica un PDF nella cartella indicata. Ritorna {id, link}."""
    svc = _service()
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/pdf", resumable=False)
    f = svc.files().create(
        body={"name": nome, "parents": [folder_id]},
        media_body=media,
        fields="id, webViewLink",
    ).execute()
    return {"id": f["id"], "link": f.get("webViewLink", "")}
