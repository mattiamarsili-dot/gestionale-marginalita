"""Gestione utenti multi-account: hashing password, CRUD, seed admin.

Gli utenti vivono nella tabella `utenti` (creata in database.py, dual DB).
Le password sono salvate come hash (werkzeug), mai in chiaro.
"""
import os

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
