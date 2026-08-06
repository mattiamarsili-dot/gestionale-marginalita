"""Gestione utenti multi-account: hashing password, CRUD, seed admin.

Gli utenti vivono nella tabella `utenti` (creata in database.py, dual DB).
Le password sono salvate come hash (werkzeug), mai in chiaro.
"""
import os
import secrets

from werkzeug.security import generate_password_hash, check_password_hash

from database import get_db, _PH, last_inserted_id

RUOLI = ["admin", "operatore"]


def utenti_esistono() -> bool:
    """True se esiste almeno un utente attivo (decide se il login è per utente
    o ancora in modalità legacy col codice unico)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM utenti WHERE attivo")
        return cur.fetchone()["n"] > 0


def lista_utenti(solo_attivi: bool = False) -> list:
    with get_db() as conn:
        cur = conn.cursor()
        where = "WHERE attivo" if solo_attivi else ""
        cur.execute(
            f"SELECT id, nome, email, ruolo, attivo, creato_il FROM utenti {where} "
            f"ORDER BY attivo DESC, nome"
        )
        return [dict(r) for r in cur.fetchall()]


def get_utente(utente_id) -> dict | None:
    try:
        uid = int(utente_id)
    except (TypeError, ValueError):
        return None
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, nome, email, ruolo, attivo FROM utenti WHERE id = {_PH}", (uid,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_utente_by_email(email: str) -> dict | None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM utenti WHERE email = {_PH}", ((email or "").strip().lower(),))
        row = cur.fetchone()
        return dict(row) if row else None


def verifica_credenziali(email: str, password: str) -> dict | None:
    """Restituisce l'utente (senza hash) se email+password sono corrette e
    l'account è attivo, altrimenti None."""
    u = get_utente_by_email(email)
    if not u or not u.get("attivo"):
        return None
    if not check_password_hash(u.get("password_hash") or "", password or ""):
        return None
    return {"id": u["id"], "nome": u["nome"], "email": u["email"], "ruolo": u["ruolo"]}


def crea_utente(nome: str, email: str, password: str, ruolo: str = "operatore") -> int:
    """Crea un utente. Solleva ValueError se l'email è già usata o mancano dati."""
    nome = (nome or "").strip()
    email = (email or "").strip().lower()
    ruolo = ruolo if ruolo in RUOLI else "operatore"
    if not nome or not email or not password:
        raise ValueError("Nome, email e password sono obbligatori.")
    if get_utente_by_email(email):
        raise ValueError("Esiste già un utente con questa email.")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO utenti (nome, email, password_hash, ruolo, attivo) "
            f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
            (nome, email, generate_password_hash(password), ruolo, True),
        )
        return last_inserted_id(cur)


def aggiorna_utente(utente_id, nome: str, ruolo: str, attivo: bool) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE utenti SET nome = {_PH}, ruolo = {_PH}, attivo = {_PH} WHERE id = {_PH}",
            ((nome or "").strip(), ruolo if ruolo in RUOLI else "operatore",
             bool(attivo), int(utente_id)),
        )


def reset_password(utente_id, nuova_password: str) -> None:
    if not (nuova_password or "").strip():
        raise ValueError("La password non può essere vuota.")
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE utenti SET password_hash = {_PH} WHERE id = {_PH}",
            (generate_password_hash(nuova_password), int(utente_id)),
        )


def genera_codice_telegram(utente_id) -> str:
    """Genera (o rigenera) un codice una-tantum per collegare l'account Telegram
    dell'utente. Restituisce il codice da comunicare alla persona."""
    codice = secrets.token_hex(3).upper()  # 6 caratteri, facile da digitare
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE utenti SET telegram_link_code = {_PH} WHERE id = {_PH}",
            (codice, int(utente_id)),
        )
    return codice


def collega_telegram(codice: str, chat_id) -> dict | None:
    """Collega un chat-id Telegram all'utente che possiede quel codice.
    Consuma il codice (lo azzera). Restituisce l'utente collegato o None."""
    codice = (codice or "").strip().upper()
    if not codice:
        return None
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, nome FROM utenti WHERE telegram_link_code = {_PH} AND attivo",
            (codice,))
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            f"UPDATE utenti SET telegram_chat_id = {_PH}, telegram_link_code = NULL WHERE id = {_PH}",
            (str(chat_id), row["id"]),
        )
        return {"id": row["id"], "nome": row["nome"]}


def scollega_telegram(utente_id) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE utenti SET telegram_chat_id = NULL, telegram_link_code = NULL WHERE id = {_PH}",
            (int(utente_id),))


def get_utente_by_chat_id(chat_id) -> dict | None:
    """Restituisce l'utente attivo collegato a un chat-id Telegram, o None."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, nome, email, ruolo FROM utenti "
            f"WHERE telegram_chat_id = {_PH} AND attivo", (str(chat_id),))
        row = cur.fetchone()
        return dict(row) if row else None


def chat_id_utente(utente_id):
    """Restituisce il chat-id Telegram di un utente (o None se non collegato)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT telegram_chat_id FROM utenti WHERE id = {_PH}", (int(utente_id),))
        row = cur.fetchone()
        return (row["telegram_chat_id"] if row else None) or None


def seed_admin() -> int:
    """Crea il primo admin da variabili d'ambiente se non esiste ancora nessun
    utente. Idempotente. Restituisce 1 se creato, 0 altrimenti."""
    if utenti_esistono():
        return 0
    email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    nome = (os.environ.get("ADMIN_NOME") or "Amministratore").strip()
    if not email or not password:
        return 0
    crea_utente(nome, email, password, ruolo="admin")
    return 1
