"""
Backup completo del database (Neon o SQLite) in un unico file JSON.

A differenza della versione precedente, è **schema-agnostico**: esporta TUTTE le
tabelle elencate in TABLES con TUTTE le loro colonne (lette dal DB a runtime).
Aggiungendo colonne nuove non serve toccare questo file; aggiungendo una tabella
nuova basta inserirla in TABLES.

Uso da terminale:
    python3 backup.py

È anche importato da app.py per il download del backup dall'app (1 click).
"""
import json
import os
import sys
from datetime import datetime, date
from decimal import Decimal

# Carica .env se presente (per DATABASE_URL in locale)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_db, _IS_POSTGRES

# Ordine FK-safe: i genitori prima dei figli (conta per il restore).
TABLES = [
    "clienti",
    "pratiche",
    "preventivi",
    "righe_ausili",
    "preset_ausili",
    "preset_righe",
    "significato_catalogo",
]


def _row_to_dict(row) -> dict:
    """Converte una riga (sqlite3.Row o dict psycopg) in dict semplice."""
    return {k: row[k] for k in row.keys()}


def _default(o):
    """Serializza i tipi non-JSON (date, datetime, Decimal)."""
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (bytes, bytearray)):
        return o.decode("utf-8", "replace")
    return str(o)


def dump_data() -> dict:
    """Estrae tutte le tabelle in un dict pronto da serializzare in JSON."""
    data = {
        "backup_date": datetime.now().isoformat(),
        "source": "postgresql" if _IS_POSTGRES else "sqlite",
        "tables": {},
    }
    with get_db() as conn:
        cur = conn.cursor()
        for t in TABLES:
            try:
                cur.execute(f"SELECT * FROM {t} ORDER BY id")
            except Exception:
                # Tabella non ancora presente su questo DB: la salto.
                conn.rollback()
                continue
            data["tables"][t] = [_row_to_dict(r) for r in cur.fetchall()]
    return data


def dump_json(indent: int = 2) -> str:
    """Backup completo come stringa JSON (usato anche dalla route di download)."""
    return json.dumps(dump_data(), ensure_ascii=False, indent=indent, default=_default)


def backup() -> str:
    """Scrive il backup su file con timestamp e restituisce il nome file."""
    data = dump_data()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"backup_{timestamp}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2, default=_default))

    print(f"Backup completato: {output_file}  ({data['source']})")
    for t in TABLES:
        if t in data["tables"]:
            print(f"  {t:22} {len(data['tables'][t]):>5}")
    return output_file


if __name__ == "__main__":
    backup()
