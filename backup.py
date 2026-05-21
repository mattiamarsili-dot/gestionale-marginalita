"""
Esporta tutti i dati dal database (Neon o SQLite) in un file JSON con timestamp.
Uso: python3 backup.py
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Carica .env se presente
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SQLITE_PATH  = os.environ.get("SQLITE_PATH", "gestionale.db")

def backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"backup_{timestamp}.json"

    if DATABASE_URL:
        print(f"Connessione a PostgreSQL (Neon)...")
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    else:
        print(f"Connessione a SQLite ({SQLITE_PATH})...")
        import sqlite3
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row

    try:
        cur = conn.cursor()

        cur.execute("SELECT * FROM pratiche ORDER BY id")
        pratiche = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM preventivi ORDER BY id")
        preventivi = [dict(r) for r in cur.fetchall()]

        # Converti campi non serializzabili (date, datetime)
        def serialize(obj):
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            return str(obj)

        data = {
            "backup_date": datetime.now().isoformat(),
            "source": "postgresql" if DATABASE_URL else "sqlite",
            "pratiche": json.loads(json.dumps(pratiche, default=serialize)),
            "preventivi": json.loads(json.dumps(preventivi, default=serialize)),
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"\nBackup completato: {output_file}")
        print(f"  Pratiche:   {len(pratiche)}")
        print(f"  Preventivi: {len(preventivi)}")

    finally:
        conn.close()

if __name__ == "__main__":
    backup()
