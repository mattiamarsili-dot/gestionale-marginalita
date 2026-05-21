"""
Ripristina i dati da un file JSON di backup nel database.
Uso: python3 restore.py backup_20240521_120000.json

ATTENZIONE: sovrascrive tutti i dati esistenti nel database di destinazione.
"""
import json
import os
import sys
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SQLITE_PATH  = os.environ.get("SQLITE_PATH", "gestionale.db")

def restore(backup_file: str):
    if not os.path.exists(backup_file):
        print(f"Errore: file {backup_file} non trovato.")
        sys.exit(1)

    with open(backup_file, encoding="utf-8") as f:
        data = json.load(f)

    pratiche   = data.get("pratiche", [])
    preventivi = data.get("preventivi", [])
    backup_date = data.get("backup_date", "?")

    print(f"Backup del: {backup_date}")
    print(f"Pratiche:   {len(pratiche)}")
    print(f"Preventivi: {len(preventivi)}")
    print()

    risposta = input("Confermi il ripristino? Tutti i dati esistenti verranno CANCELLATI. (s/N): ").strip().lower()
    if risposta != "s":
        print("Operazione annullata.")
        sys.exit(0)

    if DATABASE_URL:
        print("Connessione a PostgreSQL (Neon)...")
        import psycopg
        conn = psycopg.connect(DATABASE_URL)
        ph = "%s"
    else:
        print(f"Connessione a SQLite ({SQLITE_PATH})...")
        import sqlite3
        conn = sqlite3.connect(SQLITE_PATH)
        ph = "?"

    try:
        cur = conn.cursor()

        # Svuota tabelle
        cur.execute("DELETE FROM preventivi")
        cur.execute("DELETE FROM pratiche")

        # Ripristina pratiche
        for p in pratiche:
            cur.execute(
                f"INSERT INTO pratiche (id, nome_paziente, data_pratica, importo_asl, "
                f"provvigione_pct, note, fatturata, data_fatturazione, creato_il) "
                f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                (p["id"], p["nome_paziente"], p["data_pratica"], p["importo_asl"],
                 p.get("provvigione_pct", 0.16), p.get("note"),
                 p.get("fatturata", False), p.get("data_fatturazione"), p.get("creato_il"))
            )

        # Ripristina preventivi
        for pr in preventivi:
            cur.execute(
                f"INSERT INTO preventivi (id, pratica_id, nome_fornitore, importo, file_pdf, drive_file_id) "
                f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph})",
                (pr["id"], pr["pratica_id"], pr["nome_fornitore"], pr["importo"],
                 pr.get("file_pdf"), pr.get("drive_file_id"))
            )

        # Reset sequenza PostgreSQL
        if DATABASE_URL:
            cur.execute("SELECT setval('pratiche_id_seq', COALESCE((SELECT MAX(id) FROM pratiche), 1))")
            cur.execute("SELECT setval('preventivi_id_seq', COALESCE((SELECT MAX(id) FROM preventivi), 1))")

        conn.commit()
        print(f"\nRipristino completato.")
        print(f"  Pratiche:   {len(pratiche)} importate")
        print(f"  Preventivi: {len(preventivi)} importati")

    except Exception as e:
        conn.rollback()
        print(f"Errore durante il ripristino: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 restore.py <file_backup.json>")
        print("Esempio: python3 restore.py backup_20240521_120000.json")
        sys.exit(1)
    restore(sys.argv[1])
