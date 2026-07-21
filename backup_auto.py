"""
Backup automatico schedulabile: genera il backup JSON completo (via backup.py)
e lo recapita FUORI dal sistema, senza intervento manuale.

Destinazioni (cumulabili, tutte opzionali):
  1. Email (SMTP)          — se SMTP_HOST + BACKUP_EMAIL_TO sono impostati.
  2. Copia locale ruotata  — sempre; tiene solo le ultime BACKUP_KEEP copie.

Pensato per girare NON interattivo da GitHub Actions o Render Cron. Legge il DB
da DATABASE_URL (Neon) se presente, altrimenti dal SQLite locale — quindi in
produzione fa il backup dei dati veri di Neon.

Uso:
    python backup_auto.py

Esce con codice 0 se almeno una destinazione ha ricevuto il backup, 1 altrimenti.
"""
import glob
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage

# Carica .env in locale (in CI/Render le variabili arrivano dall'ambiente)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from backup import dump_json
from config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    BACKUP_EMAIL_TO, BACKUP_EMAIL_FROM, BACKUP_DIR, BACKUP_KEEP,
    DATABASE_URL,
)


def _nome_file() -> str:
    return f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"


def _scrivi_locale(nome: str, contenuto: str) -> str:
    """Scrive la copia locale e ruota tenendo solo le ultime BACKUP_KEEP."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    percorso = os.path.join(BACKUP_DIR, nome)
    with open(percorso, "w", encoding="utf-8") as f:
        f.write(contenuto)

    # Rotazione: elimina le copie più vecchie oltre BACKUP_KEEP.
    copie = sorted(glob.glob(os.path.join(BACKUP_DIR, "backup_*.json")))
    for vecchia in copie[:-BACKUP_KEEP] if BACKUP_KEEP > 0 else []:
        try:
            os.remove(vecchia)
        except OSError:
            pass
    return percorso


def _invia_email(nome: str, contenuto: str) -> None:
    """Invia il backup come allegato via SMTP (STARTTLS o SSL a seconda della porta)."""
    origine = "Neon (produzione)" if DATABASE_URL else "SQLite (locale)"
    msg = EmailMessage()
    msg["Subject"] = f"Backup Gestionale Marginalità — {nome}"
    msg["From"] = BACKUP_EMAIL_FROM
    msg["To"] = BACKUP_EMAIL_TO
    msg.set_content(
        "Backup automatico del Gestionale Marginalità in allegato.\n\n"
        f"File:    {nome}\n"
        f"Origine: {origine}\n"
        f"Data:    {datetime.now().isoformat(timespec='seconds')}\n\n"
        "Conserva questo file: è il backup completo (clienti, pratiche, preventivi, "
        "righe ausili, preset, note). Ripristinabile con:  python restore.py <file>\n"
    )
    msg.add_attachment(
        contenuto.encode("utf-8"),
        maintype="application",
        subtype="json",
        filename=nome,
    )

    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context()) as s:
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls(context=ssl.create_default_context())
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)


def run() -> int:
    nome = _nome_file()
    contenuto = dump_json()
    kb = len(contenuto.encode("utf-8")) / 1024
    print(f"Backup generato: {nome} ({kb:.1f} KB, origine "
          f"{'Neon' if DATABASE_URL else 'SQLite locale'})")

    recapitato = False

    # 1) Copia locale ruotata (sempre)
    try:
        percorso = _scrivi_locale(nome, contenuto)
        print(f"  ✓ copia locale: {percorso}  (tengo le ultime {BACKUP_KEEP})")
        recapitato = True
    except Exception as e:
        print(f"  ✗ copia locale fallita: {e}", file=sys.stderr)

    # 2) Email (solo se configurata)
    if SMTP_HOST and BACKUP_EMAIL_TO:
        try:
            _invia_email(nome, contenuto)
            print(f"  ✓ email inviata a {BACKUP_EMAIL_TO}")
            recapitato = True
        except Exception as e:
            print(f"  ✗ invio email fallito: {e}", file=sys.stderr)
    else:
        print("  · email saltata (SMTP_HOST/BACKUP_EMAIL_TO non impostati)")

    if not recapitato:
        print("Nessuna destinazione ha ricevuto il backup.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
