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
    CREATE TABLE IF NOT EXISTS clienti (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        cognome                 TEXT NOT NULL,
        nome                    TEXT NOT NULL DEFAULT '',
        codice_fiscale          TEXT,
        data_nascita            DATE,
        luogo_nascita           TEXT,
        provincia               TEXT,
        residenza_via           TEXT,
        residenza_civico        TEXT,
        residenza_citta         TEXT,
        residenza_cap           TEXT,
        residente_dal_anno      TEXT,
        telefono                TEXT,
        email                   TEXT,
        asl                     TEXT,
        centro                  TEXT,
        medico_curante          TEXT,
        decorrenza_residenza    DATE,
        documento_tipo_numero   TEXT,
        documento_rilascio_luogo TEXT,
        documento_data_rilascio DATE,
        ha_tutore                       INTEGER NOT NULL DEFAULT 0,
        tutore_nome                     TEXT,
        tutore_cf                       TEXT,
        tutore_documento_tipo_numero    TEXT,
        tutore_documento_rilascio_luogo TEXT,
        tutore_documento_rilascio_data  DATE,
        da_verificare           INTEGER NOT NULL DEFAULT 0,
        note                    TEXT,
        creato_il               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS pratiche (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        nome_paziente    TEXT NOT NULL,
        cliente_id       INTEGER,
        data_pratica     DATE NOT NULL,
        importo_asl      REAL NOT NULL,
        importo_privato  REAL NOT NULL DEFAULT 0,
        provvigione_pct  REAL NOT NULL DEFAULT 0.16,
        note             TEXT,
        fatturata        INTEGER NOT NULL DEFAULT 0,
        data_fatturazione DATE,
        numero_pratica   TEXT,
        ausilio          TEXT,
        asl_destinataria TEXT,
        medico_struttura TEXT,
        diagnosi         TEXT,
        sign_terapeutico TEXT,
        iva_percentuale  REAL NOT NULL DEFAULT 4,
        moduli_attivi    TEXT,
        moduli_generati  TEXT,
        stato_lavorazione TEXT NOT NULL DEFAULT 'Segnalato',
        tipologia        TEXT,
        drive_archivio_id TEXT,
        creato_il        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (cliente_id) REFERENCES clienti(id)
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

    CREATE TABLE IF NOT EXISTS righe_ausili (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        pratica_id      INTEGER NOT NULL,
        codice_iso      TEXT,
        descrizione     TEXT,
        qta             REAL NOT NULL DEFAULT 1,
        prezzo_unitario REAL NOT NULL DEFAULT 0,
        ordine          INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (pratica_id) REFERENCES pratiche(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS preset_ausili (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        label     TEXT NOT NULL,
        categoria TEXT
    );

    CREATE TABLE IF NOT EXISTS preset_righe (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        preset_id       INTEGER NOT NULL,
        codice_iso      TEXT,
        descrizione     TEXT,
        qta             REAL NOT NULL DEFAULT 1,
        prezzo_unitario REAL NOT NULL DEFAULT 0,
        ordine          INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (preset_id) REFERENCES preset_ausili(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS significato_catalogo (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        articolo  TEXT NOT NULL,
        testo     TEXT NOT NULL,
        ordine    INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS note (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id   INTEGER,
        nominativo   TEXT NOT NULL DEFAULT '',
        tipo         TEXT NOT NULL DEFAULT 'Assistenza',
        sottotipo    TEXT NOT NULL DEFAULT '',
        priorita     TEXT NOT NULL DEFAULT 'Media',
        stato        TEXT NOT NULL DEFAULT 'Aperta',
        completata   INTEGER NOT NULL DEFAULT 0,
        testo        TEXT NOT NULL DEFAULT '',
        scadenza     DATE,
        creato_il    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (cliente_id) REFERENCES clienti(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS app_config (
        chiave  TEXT PRIMARY KEY,
        valore  TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_pratiche_data      ON pratiche(data_pratica);
    CREATE INDEX IF NOT EXISTS idx_preventivi_pratica ON preventivi(pratica_id);
    CREATE INDEX IF NOT EXISTS idx_righe_pratica      ON righe_ausili(pratica_id);
    CREATE INDEX IF NOT EXISTS idx_preset_righe       ON preset_righe(preset_id);
    CREATE INDEX IF NOT EXISTS idx_clienti_cognome    ON clienti(cognome);
    CREATE INDEX IF NOT EXISTS idx_clienti_cf         ON clienti(codice_fiscale);
    CREATE INDEX IF NOT EXISTS idx_sign_articolo      ON significato_catalogo(articolo);
    CREATE INDEX IF NOT EXISTS idx_note_cliente       ON note(cliente_id);
    CREATE INDEX IF NOT EXISTS idx_note_completata    ON note(completata);
    CREATE INDEX IF NOT EXISTS idx_note_scadenza      ON note(scadenza);
"""

_POSTGRES_SCHEMA = """
    CREATE TABLE IF NOT EXISTS clienti (
        id                      SERIAL PRIMARY KEY,
        cognome                 TEXT NOT NULL,
        nome                    TEXT NOT NULL DEFAULT '',
        codice_fiscale          TEXT,
        data_nascita            DATE,
        luogo_nascita           TEXT,
        provincia               TEXT,
        residenza_via           TEXT,
        residenza_civico        TEXT,
        residenza_citta         TEXT,
        residenza_cap           TEXT,
        residente_dal_anno      TEXT,
        telefono                TEXT,
        email                   TEXT,
        asl                     TEXT,
        centro                  TEXT,
        medico_curante          TEXT,
        decorrenza_residenza    DATE,
        documento_tipo_numero   TEXT,
        documento_rilascio_luogo TEXT,
        documento_data_rilascio DATE,
        ha_tutore                       BOOLEAN NOT NULL DEFAULT FALSE,
        tutore_nome                     TEXT,
        tutore_cf                       TEXT,
        tutore_documento_tipo_numero    TEXT,
        tutore_documento_rilascio_luogo TEXT,
        tutore_documento_rilascio_data  DATE,
        da_verificare           BOOLEAN NOT NULL DEFAULT FALSE,
        note                    TEXT,
        creato_il               TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS pratiche (
        id               SERIAL PRIMARY KEY,
        nome_paziente    TEXT NOT NULL,
        cliente_id       INTEGER REFERENCES clienti(id),
        data_pratica     DATE NOT NULL,
        importo_asl      REAL NOT NULL,
        importo_privato  REAL NOT NULL DEFAULT 0,
        provvigione_pct  REAL NOT NULL DEFAULT 0.16,
        note             TEXT,
        fatturata        BOOLEAN NOT NULL DEFAULT FALSE,
        data_fatturazione DATE,
        numero_pratica   TEXT,
        ausilio          TEXT,
        asl_destinataria TEXT,
        medico_struttura TEXT,
        diagnosi         TEXT,
        sign_terapeutico TEXT,
        iva_percentuale  REAL NOT NULL DEFAULT 4,
        moduli_attivi    TEXT,
        moduli_generati  TEXT,
        stato_lavorazione TEXT NOT NULL DEFAULT 'Segnalato',
        tipologia        TEXT,
        drive_archivio_id TEXT,
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

    CREATE TABLE IF NOT EXISTS righe_ausili (
        id              SERIAL PRIMARY KEY,
        pratica_id      INTEGER NOT NULL,
        codice_iso      TEXT,
        descrizione     TEXT,
        qta             REAL NOT NULL DEFAULT 1,
        prezzo_unitario REAL NOT NULL DEFAULT 0,
        ordine          INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (pratica_id) REFERENCES pratiche(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS preset_ausili (
        id        SERIAL PRIMARY KEY,
        label     TEXT NOT NULL,
        categoria TEXT
    );

    CREATE TABLE IF NOT EXISTS preset_righe (
        id              SERIAL PRIMARY KEY,
        preset_id       INTEGER NOT NULL,
        codice_iso      TEXT,
        descrizione     TEXT,
        qta             REAL NOT NULL DEFAULT 1,
        prezzo_unitario REAL NOT NULL DEFAULT 0,
        ordine          INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (preset_id) REFERENCES preset_ausili(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS significato_catalogo (
        id        SERIAL PRIMARY KEY,
        articolo  TEXT NOT NULL,
        testo     TEXT NOT NULL,
        ordine    INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS note (
        id           SERIAL PRIMARY KEY,
        cliente_id   INTEGER REFERENCES clienti(id) ON DELETE SET NULL,
        nominativo   TEXT NOT NULL DEFAULT '',
        tipo         TEXT NOT NULL DEFAULT 'Assistenza',
        sottotipo    TEXT NOT NULL DEFAULT '',
        priorita     TEXT NOT NULL DEFAULT 'Media',
        stato        TEXT NOT NULL DEFAULT 'Aperta',
        completata   BOOLEAN NOT NULL DEFAULT FALSE,
        testo        TEXT NOT NULL DEFAULT '',
        scadenza     DATE,
        creato_il    TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS app_config (
        chiave  TEXT PRIMARY KEY,
        valore  TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_pratiche_data      ON pratiche(data_pratica);
    CREATE INDEX IF NOT EXISTS idx_preventivi_pratica ON preventivi(pratica_id);
    CREATE INDEX IF NOT EXISTS idx_righe_pratica      ON righe_ausili(pratica_id);
    CREATE INDEX IF NOT EXISTS idx_preset_righe       ON preset_righe(preset_id);
    CREATE INDEX IF NOT EXISTS idx_clienti_cognome    ON clienti(cognome);
    CREATE INDEX IF NOT EXISTS idx_clienti_cf         ON clienti(codice_fiscale);
    CREATE INDEX IF NOT EXISTS idx_sign_articolo      ON significato_catalogo(articolo);
    CREATE INDEX IF NOT EXISTS idx_note_cliente       ON note(cliente_id);
    CREATE INDEX IF NOT EXISTS idx_note_completata    ON note(completata);
    CREATE INDEX IF NOT EXISTS idx_note_scadenza      ON note(scadenza);
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
    """Aggiunge colonne/indici mancanti a DB già esistenti (idempotente).

    IMPORTANTE: ogni statement gira nella PROPRIA transazione (un `get_db()` a
    testa). Su PostgreSQL un singolo errore aborta solo la sua transazione, non
    inquina le altre: così una colonna problematica non fa perdere tutte le
    successive (com'era col vecchio batch in un'unica transazione)."""
    if _IS_POSTGRES:
        statements = [
            "ALTER TABLE preventivi ADD COLUMN IF NOT EXISTS drive_file_id TEXT",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS provvigione_pct REAL DEFAULT 0.16",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS fatturata BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS data_fatturazione DATE",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS importo_privato REAL NOT NULL DEFAULT 0",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS cliente_id INTEGER REFERENCES clienti(id)",
            "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS centro TEXT",
            "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS residente_dal_anno TEXT",
            "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS ha_tutore BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS tutore_nome TEXT",
            "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS tutore_cf TEXT",
            "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS tutore_documento_tipo_numero TEXT",
            "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS tutore_documento_rilascio_luogo TEXT",
            "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS tutore_documento_rilascio_data DATE",
            "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS documento_rilascio_luogo TEXT",
            "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS da_verificare BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS numero_pratica TEXT",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS ausilio TEXT",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS asl_destinataria TEXT",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS medico_struttura TEXT",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS diagnosi TEXT",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS sign_terapeutico TEXT",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS iva_percentuale REAL NOT NULL DEFAULT 4",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS moduli_attivi TEXT",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS moduli_generati TEXT",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS stato_lavorazione TEXT NOT NULL DEFAULT 'Segnalato'",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS tipologia TEXT",
            "ALTER TABLE pratiche ADD COLUMN IF NOT EXISTS drive_archivio_id TEXT",
            "ALTER TABLE note ADD COLUMN IF NOT EXISTS sottotipo TEXT NOT NULL DEFAULT ''",
        ]
    else:
        statements = [
            "ALTER TABLE preventivi ADD COLUMN drive_file_id TEXT",
            "ALTER TABLE pratiche ADD COLUMN provvigione_pct REAL DEFAULT 0.16",
            "ALTER TABLE pratiche ADD COLUMN fatturata INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pratiche ADD COLUMN data_fatturazione DATE",
            "ALTER TABLE pratiche ADD COLUMN importo_privato REAL NOT NULL DEFAULT 0",
            "ALTER TABLE pratiche ADD COLUMN cliente_id INTEGER REFERENCES clienti(id)",
            "ALTER TABLE clienti ADD COLUMN centro TEXT",
            "ALTER TABLE clienti ADD COLUMN residente_dal_anno TEXT",
            "ALTER TABLE clienti ADD COLUMN ha_tutore INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE clienti ADD COLUMN tutore_nome TEXT",
            "ALTER TABLE clienti ADD COLUMN tutore_cf TEXT",
            "ALTER TABLE clienti ADD COLUMN tutore_documento_tipo_numero TEXT",
            "ALTER TABLE clienti ADD COLUMN tutore_documento_rilascio_luogo TEXT",
            "ALTER TABLE clienti ADD COLUMN tutore_documento_rilascio_data DATE",
            "ALTER TABLE clienti ADD COLUMN documento_rilascio_luogo TEXT",
            "ALTER TABLE clienti ADD COLUMN da_verificare INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pratiche ADD COLUMN numero_pratica TEXT",
            "ALTER TABLE pratiche ADD COLUMN ausilio TEXT",
            "ALTER TABLE pratiche ADD COLUMN asl_destinataria TEXT",
            "ALTER TABLE pratiche ADD COLUMN medico_struttura TEXT",
            "ALTER TABLE pratiche ADD COLUMN diagnosi TEXT",
            "ALTER TABLE pratiche ADD COLUMN sign_terapeutico TEXT",
            "ALTER TABLE pratiche ADD COLUMN iva_percentuale REAL NOT NULL DEFAULT 4",
            "ALTER TABLE pratiche ADD COLUMN moduli_attivi TEXT",
            "ALTER TABLE pratiche ADD COLUMN moduli_generati TEXT",
            "ALTER TABLE pratiche ADD COLUMN stato_lavorazione TEXT NOT NULL DEFAULT 'Segnalato'",
            "ALTER TABLE pratiche ADD COLUMN tipologia TEXT",
            "ALTER TABLE pratiche ADD COLUMN drive_archivio_id TEXT",
            "ALTER TABLE note ADD COLUMN sottotipo TEXT NOT NULL DEFAULT ''",
        ]

    # Indici: la colonna cliente_id viene aggiunta dagli ALTER qui sopra.
    statements += [
        "CREATE INDEX IF NOT EXISTS idx_pratiche_cliente ON pratiche(cliente_id)",
        "CREATE INDEX IF NOT EXISTS idx_clienti_centro ON clienti(centro)",
    ]

    for ddl in statements:
        try:
            with get_db() as conn:        # una transazione per statement
                conn.cursor().execute(ddl)
        except Exception:
            pass  # colonna/indice già presente o non applicabile: si prosegue


def backfill_clienti() -> int:
    """
    Crea un cliente per ogni `nome_paziente` distinto delle pratiche non ancora
    collegate e imposta `pratiche.cliente_id`. Idempotente: riusa il cliente già
    creato in un run precedente (match per `cognome` == nome_paziente originale).

    Il nome libero finisce in `cognome` (con `nome` vuoto): la separazione
    cognome/nome non è affidabile sul testo libero, l'utente potrà correggere
    dalla scheda anagrafica. Restituisce il numero di clienti creati.
    """
    creati = 0
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT DISTINCT nome_paziente FROM pratiche "
            f"WHERE cliente_id IS NULL AND nome_paziente IS NOT NULL "
            f"AND TRIM(nome_paziente) <> ''"
        )
        nomi = [r["nome_paziente"] for r in cur.fetchall()]

        for nome in nomi:
            nome_norm = nome.strip()
            # Riusa un cliente già creato dal backfill (cognome == nome originale, nome vuoto)
            cur.execute(
                f"SELECT id FROM clienti WHERE cognome = {_PH} AND (nome = '' OR nome IS NULL) "
                f"ORDER BY id LIMIT 1",
                (nome_norm,),
            )
            row = cur.fetchone()
            if row:
                cliente_id = row["id"]
            else:
                cur.execute(
                    f"INSERT INTO clienti (cognome, nome, note) VALUES ({_PH}, '', {_PH})",
                    (nome_norm, "Creato automaticamente dalla migrazione pratiche"),
                )
                cliente_id = last_inserted_id(cur)
                creati += 1

            cur.execute(
                f"UPDATE pratiche SET cliente_id = {_PH} "
                f"WHERE cliente_id IS NULL AND nome_paziente = {_PH}",
                (cliente_id, nome_norm),
            )
    return creati

# ── Helper DB ─────────────────────────────────────────────────────────────────

def last_inserted_id(cur) -> int:
    """Restituisce l'id dell'ultimo INSERT (dialetto SQLite / PostgreSQL)."""
    if _IS_POSTGRES:
        cur.execute("SELECT lastval()")
        return cur.fetchone()["lastval"]
    return cur.lastrowid


# ── Impostazioni chiave/valore (tabella app_config) ──────────────────────────

def config_get(chiave: str, default=None):
    """Legge un valore da app_config (None/default se assente)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT valore FROM app_config WHERE chiave = {_PH}", (chiave,))
        row = cur.fetchone()
    return row["valore"] if row else default


def config_set(chiave: str, valore):
    """Scrive (upsert) un valore in app_config. valore None → rimuove la chiave."""
    with get_db() as conn:
        cur = conn.cursor()
        if valore is None:
            cur.execute(f"DELETE FROM app_config WHERE chiave = {_PH}", (chiave,))
            return
        if _IS_POSTGRES:
            cur.execute(
                "INSERT INTO app_config (chiave, valore) VALUES (%s, %s) "
                "ON CONFLICT (chiave) DO UPDATE SET valore = EXCLUDED.valore",
                (chiave, valore),
            )
        else:
            cur.execute(
                "INSERT INTO app_config (chiave, valore) VALUES (?, ?) "
                "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore",
                (chiave, valore),
            )

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
