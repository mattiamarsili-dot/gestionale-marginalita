import sqlite3
from contextlib import contextmanager
from config import (
    PROVVIGIONE_PCT, PROVVIGIONE_PCT_17, PROVVIGIONE_PCT_18,
    STRUTTURA_PCT, SOGLIA_PROV_17, SOGLIA_PROV_18,
    DATABASE_URL, SQLITE_PATH,
)

# ── Costanti di connessione (calcolate una volta all'avvio) ──────────────────

_IS_POSTGRES: bool = bool(DATABASE_URL)
_PH: str = "%s" if _IS_POSTGRES else "?"

# Fix PostgreSQL: TO_CHAR restituisce "05" (zero-padded), EXTRACT restituisce 5
_DATE_FILTER: str = (
    "TO_CHAR(p.data_pratica, 'YYYY') = {ph} AND TO_CHAR(p.data_pratica, 'MM') = {ph}"
    if _IS_POSTGRES else
    "strftime('%Y', p.data_pratica) = {ph} AND strftime('%m', p.data_pratica) = {ph}"
).format(ph=_PH)

# Formato mese per SELECT DISTINCT (YYYY-MM)
_MONTH_FORMAT: str = (
    "TO_CHAR(data_pratica, 'YYYY-MM')"
    if _IS_POSTGRES else
    "strftime('%Y-%m', data_pratica)"
)

# Valore booleano TRUE compatibile con entrambi i dialetti
_FATTURATA_TRUE: str = "TRUE" if _IS_POSTGRES else "1"

# ── Connessione ───────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    if _IS_POSTGRES:
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ── Schema ────────────────────────────────────────────────────────────────────

_SQLITE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS pratiche (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nome_paziente    TEXT NOT NULL,
        data_pratica     DATE NOT NULL,
        importo_asl      REAL NOT NULL,
        importo_privato  REAL NOT NULL DEFAULT 0,
        provvigione_pct  REAL NOT NULL DEFAULT 0.16,
        note             TEXT,
        fatturata        INTEGER NOT NULL DEFAULT 0,
        data_fatturazione DATE,
        creato_il        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS preventivi (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        pratica_id     INTEGER NOT NULL,
        nome_fornitore TEXT NOT NULL,
        importo        REAL NOT NULL,
        file_pdf       TEXT,
        drive_file_id  TEXT,
        FOREIGN KEY (pratica_id) REFERENCES pratiche(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_pratiche_data      ON pratiche(data_pratica);
    CREATE INDEX IF NOT EXISTS idx_preventivi_pratica ON preventivi(pratica_id);
"""

_POSTGRES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS pratiche (
        id               SERIAL PRIMARY KEY,
        nome_paziente    TEXT NOT NULL,
        data_pratica     DATE NOT NULL,
        importo_asl      REAL NOT NULL,
        importo_privato  REAL NOT NULL DEFAULT 0,
        provvigione_pct  REAL NOT NULL DEFAULT 0.16,
        note             TEXT,
        fatturata        BOOLEAN NOT NULL DEFAULT FALSE,
        data_fatturazione DATE,
        creato_il        TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS preventivi (
        id             SERIAL PRIMARY KEY,
        pratica_id     INTEGER NOT NULL,
        nome_fornitore TEXT NOT NULL,
        importo        REAL NOT NULL,
        file_pdf       TEXT,
        drive_file_id  TEXT,
        FOREIGN KEY (pratica_id) REFERENCES pratiche(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_pratiche_data      ON pratiche(data_pratica);
    CREATE INDEX IF NOT EXISTS idx_preventivi_pratica ON preventivi(pratica_id);
"""

def init_db():
    schema = _POSTGRES_SCHEMA if _IS_POSTGRES else _SQLITE_SCHEMA
    with get_db() as conn:
        cur = conn.cursor()
        if _IS_POSTGRES:
            for stmt in schema.split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
        else:
            conn.executescript(schema)

def migrate_db():
    """Aggiunge colonne mancanti a DB già esistenti (idempotente)."""
    with get_db() as conn:
        cur = conn.cursor()
        if _IS_POSTGRES:
            cur.execute(
                "ALTER TABLE preventivi ADD COLUMN IF NOT EXISTS drive_file_id TEXT"
            )
            cur.execute(
                "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS provvigione_pct REAL DEFAULT 0.16"
            )
            cur.execute(
                "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS fatturata BOOLEAN NOT NULL DEFAULT FALSE"
            )
            cur.execute(
                "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS data_fatturazione DATE"
            )
            cur.execute(
                "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS importo_privato REAL NOT NULL DEFAULT 0"
            )
        else:
            for ddl in [
                "ALTER TABLE preventivi ADD COLUMN drive_file_id TEXT",
                "ALTER TABLE pratiche ADD COLUMN provvigione_pct REAL DEFAULT 0.16",
                "ALTER TABLE pratiche ADD COLUMN fatturata INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE pratiche ADD COLUMN data_fatturazione DATE",
                "ALTER TABLE pratiche ADD COLUMN importo_privato REAL NOT NULL DEFAULT 0",
            ]:
                try:
                    cur.execute(ddl)
                except Exception:
                    pass  # colonna già presente

# ── Helper DB ─────────────────────────────────────────────────────────────────

def last_inserted_id(cur) -> int:
    """Restituisce l'id dell'ultimo INSERT (dialetto SQLite / PostgreSQL)."""
    if _IS_POSTGRES:
        cur.execute("SELECT lastval()")
        return cur.fetchone()["lastval"]
    return cur.lastrowid

# ── Query helpers ─────────────────────────────────────────────────────────────

# Alias per retrocompatibilità — preferire le costanti _PH e _DATE_FILTER
def _ph() -> str:
    return _PH

def date_filter_sql() -> str:
    return _DATE_FILTER

# ── Logica di business ────────────────────────────────────────────────────────

def calcola_margine(
    importo_asl: float,
    costo_totale: float,
    provvigione_pct: float = PROVVIGIONE_PCT,
    importo_privato: float = 0.0,
) -> dict:
    ricavi_totali = importo_asl + importo_privato
    provvigione   = ricavi_totali * provvigione_pct  # provvigione su totale ASL+privato
    struttura     = ricavi_totali * STRUTTURA_PCT     # struttura su totale ASL+privato
    mol           = ricavi_totali - costo_totale - provvigione - struttura
    margine_pct   = (mol / ricavi_totali * 100) if ricavi_totali > 0 else 0
    return {
        "ricavi":           importo_asl,
        "importo_privato":  importo_privato,
        "ricavi_totali":    ricavi_totali,
        "costo":            costo_totale,
        "provvigione":      provvigione,
        "provvigione_pct":  provvigione_pct * 100,
        "struttura":        struttura,
        "struttura_pct":    STRUTTURA_PCT * 100,
        "mol":              mol,
        "margine_pct":      margine_pct,
    }


def provvigione_corrente(conn) -> tuple[float, float]:
    """
    Calcola il fatturato ASL annuo (anno corrente, pratiche fatturate)
    e restituisce (totale_asl_annuo, aliquota_corrente).
    La soglia usa solo importo_asl (non privato) come da regole di business.
    """
    import datetime
    oggi = datetime.date.today()
    anno_start = f"{oggi.year}-01-01"
    anno_end   = f"{oggi.year}-12-31"
    cur = conn.cursor()
    if _IS_POSTGRES:
        cur.execute(
            "SELECT COALESCE(SUM(importo_asl), 0) AS totale FROM pratiche "
            "WHERE fatturata = TRUE "
            "AND data_fatturazione IS NOT NULL "
            "AND data_fatturazione BETWEEN %s AND %s",
            (anno_start, anno_end)
        )
    else:
        cur.execute(
            "SELECT COALESCE(SUM(importo_asl), 0) AS totale FROM pratiche "
            "WHERE fatturata = 1 "
            "AND data_fatturazione IS NOT NULL "
            "AND data_fatturazione BETWEEN ? AND ?",
            (anno_start, anno_end)
        )
    row = cur.fetchone()
    totale_asl = float(row["totale"] if row else 0)

    if totale_asl >= SOGLIA_PROV_18:
        aliquota = PROVVIGIONE_PCT_18
    elif totale_asl >= SOGLIA_PROV_17:
        aliquota = PROVVIGIONE_PCT_17
    else:
        aliquota = PROVVIGIONE_PCT
    return totale_asl, aliquota
