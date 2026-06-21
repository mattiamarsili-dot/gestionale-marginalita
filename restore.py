"""
Ripristina i dati da un file JSON di backup nel database (Neon o SQLite).

Schema-agnostico: reinserisce tutte le tabelle/colonne presenti nel backup.
Riconosce sia il nuovo formato ({"tables": {...}}) sia i vecchi backup
({"pratiche": [...], "preventivi": [...]}).

ATTENZIONE: svuota e sovrascrive le tabelle presenti nel backup.

Uso:
    python3 restore.py backup_AAAAMMGG_HHMMSS.json
"""
import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_db, _IS_POSTGRES, _PH
from backup import TABLES


def _tabelle_dal_backup(data: dict) -> dict:
    """Estrae il dict {tabella: [righe]} da nuovo o vecchio formato."""
    if "tables" in data:
        return data["tables"]
    # Vecchio formato: chiavi di primo livello = nomi tabella
    return {t: data[t] for t in TABLES if isinstance(data.get(t), list)}


def restore_into(data: dict, conn) -> dict:
    """Esegue il ripristino su una connessione aperta. Ritorna i conteggi."""
    tabelle = _tabelle_dal_backup(data)
    cur = conn.cursor()
    conteggi = {}

    # Svuota in ordine FK inverso (figli prima dei genitori).
    for t in reversed(TABLES):
        if t in tabelle:
            cur.execute(f"DELETE FROM {t}")

    # Reinserisce in ordine FK diretto.
    for t in TABLES:
        righe = tabelle.get(t) or []
        for r in righe:
            cols = list(r.keys())
            collist = ", ".join(cols)
            placeholders = ", ".join([_PH] * len(cols))
            cur.execute(
                f"INSERT INTO {t} ({collist}) VALUES ({placeholders})",
                [r.get(c) for c in cols],
            )
        conteggi[t] = len(righe)

    # Riallinea le sequenze su PostgreSQL (gli id sono stati forzati).
    if _IS_POSTGRES:
        for t in TABLES:
            if t in tabelle:
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {t}), 1))"
                )
    return conteggi


def restore(backup_file: str):
    if not os.path.exists(backup_file):
        print(f"Errore: file {backup_file} non trovato.")
        sys.exit(1)

    with open(backup_file, encoding="utf-8") as f:
        data = json.load(f)

    tabelle = _tabelle_dal_backup(data)
    print(f"Backup del: {data.get('backup_date', '?')}  (origine: {data.get('source', '?')})")
    for t in TABLES:
        if t in tabelle:
            print(f"  {t:22} {len(tabelle[t]):>5}")
    print(f"\nDestinazione: {'PostgreSQL (Neon)' if _IS_POSTGRES else 'SQLite locale'}")

    risposta = input(
        "\nConfermi il ripristino? Le tabelle elencate verranno SVUOTATE e riscritte. (s/N): "
    ).strip().lower()
    if risposta != "s":
        print("Operazione annullata.")
        sys.exit(0)

    with get_db() as conn:
        conteggi = restore_into(data, conn)

    print("\nRipristino completato:")
    for t, n in conteggi.items():
        print(f"  {t:22} {n:>5} importate")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 restore.py <file_backup.json>")
        sys.exit(1)
    restore(sys.argv[1])
