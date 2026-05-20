"""
Integrazione Google Drive per il Gestionale Marginalità.

Richiede un Service Account con accesso in lettura alla cartella Drive.
Le credenziali vengono lette da GOOGLE_CREDENTIALS_JSON (env var con il
contenuto JSON del file di service account) e DRIVE_FOLDER_ID.

Setup una-tantum:
  1. Google Cloud Console → IAM → Service Account → crea → scarica JSON
  2. Copia il contenuto del JSON nell'env var GOOGLE_CREDENTIALS_JSON
  3. Condividi la cartella Drive con l'email del service account
  4. Imposta DRIVE_FOLDER_ID con l'ID della cartella (dall'URL di Drive)
"""

import json
import os
import tempfile

from config import DRIVE_FOLDER_ID, GOOGLE_CREDENTIALS_JSON

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    _DRIVE_AVAILABLE = True
except ImportError:
    _DRIVE_AVAILABLE = False

_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


# ── Costruzione servizio ──────────────────────────────────────────────────────

def _build_service():
    if not _DRIVE_AVAILABLE:
        raise RuntimeError("google-api-python-client non installato")
    if not GOOGLE_CREDENTIALS_JSON:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON non configurato")
    if not DRIVE_FOLDER_ID:
        raise RuntimeError("DRIVE_FOLDER_ID non configurato")

    creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=_SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


# ── Query cartella ────────────────────────────────────────────────────────────

def lista_pdf_drive(importati: set[str]) -> list[dict]:
    """
    Ritorna i PDF nella cartella Drive non ancora importati.

    Args:
        importati: set di drive_file_id già presenti nel DB.

    Returns:
        Lista di dict con chiavi: id, name, createdTime.
    """
    service = _build_service()

    query = (
        f"'{DRIVE_FOLDER_ID}' in parents "
        "and mimeType='application/pdf' "
        "and trashed=false"
    )
    results = service.files().list(
        q=query,
        fields="files(id, name, createdTime)",
        orderBy="createdTime desc",
        pageSize=50,
    ).execute()

    tutti = results.get("files", [])
    return [f for f in tutti if f["id"] not in importati]


# ── Download ──────────────────────────────────────────────────────────────────

def scarica_pdf_temp(file_id: str) -> str:
    """
    Scarica un file PDF da Drive in un file temporaneo.

    Returns:
        Path del file temporaneo (da eliminare dopo l'uso).
    """
    service = _build_service()
    request = service.files().get_media(fileId=file_id)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="drive_")
    downloader = MediaIoBaseDownload(tmp, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    tmp.close()
    return tmp.name


# ── Disponibilità ─────────────────────────────────────────────────────────────

def drive_configurato() -> bool:
    """True se le credenziali e la cartella sono impostate."""
    return _DRIVE_AVAILABLE and bool(GOOGLE_CREDENTIALS_JSON) and bool(DRIVE_FOLDER_ID)
