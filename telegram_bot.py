"""
Bot Telegram del gestionale — apertura rapida, task/note, avvisi, cambio stato.

Modulo AUTOSUFFICIENTE: usa solo `database`, `config`, `utenti` (nessun import di
`app`, per evitare cicli). Le route Flask (`/telegram/webhook`, `/telegram/digest`)
vivono in app.py e delegano qui.

Chiamate HTTP a Telegram con la sola stdlib (urllib) → nessuna dipendenza nuova.

Sicurezza: solo i chat-id collegati a un utente (utenti.telegram_chat_id) possono
usare i comandi; l'onboarding avviene con `/collega <codice>` (codice generato in
"Gestione utenti"). Le risposte con dati restano minime; per il resto, link con login.
"""
import json
import re
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta

from config import (
    TELEGRAM_BOT_TOKEN, BASE_URL, STATI_LAVORAZIONE, NOTE_PRIORITA_GIORNI,
    PRATICHE_FERME_GIORNI, PRATICHE_FERME_GIORNO_SETTIMANA,
)
from database import get_db, _PH, _LIKE, _FATTURATA_TRUE, last_inserted_id
from utenti import (
    get_utente_by_chat_id, collega_telegram, chat_id_utente,
)

API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def attivo() -> bool:
    return bool(TELEGRAM_BOT_TOKEN)


# ── Livello HTTP ─────────────────────────────────────────────────────────────
def _api(method: str, payload: dict) -> dict | None:
    if not TELEGRAM_BOT_TOKEN:
        return None
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{API}/{method}", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return None
    except Exception:
        return None


def _kb(rows):
    """Costruisce una inline keyboard. `rows` = lista di righe; ogni bottone è
    (testo, {'cb': dato}) per callback oppure (testo, {'url': link})."""
    keyboard = []
    for row in rows:
        r = []
        for testo, act in row:
            btn = {"text": testo}
            if "cb" in act:
                btn["callback_data"] = act["cb"]
            elif "url" in act:
                btn["url"] = act["url"]
            r.append(btn)
        if r:
            keyboard.append(r)
    return {"inline_keyboard": keyboard}


def send_message(chat_id, text, rows=None, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    elif rows:
        payload["reply_markup"] = _kb(rows)
    return _api("sendMessage", payload)


def edit_message(chat_id, message_id, text, rows=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": True}
    if rows:
        payload["reply_markup"] = _kb(rows)
    return _api("editMessageText", payload)


def answer_callback(cb_id, text=None):
    payload = {"callback_query_id": cb_id}
    if text:
        payload["text"] = text
    return _api("answerCallbackQuery", payload)


def set_webhook(url, secret=""):
    payload = {"url": url, "allowed_updates": ["message", "callback_query"]}
    if secret:
        payload["secret_token"] = secret
    return _api("setWebhook", payload)


# Menu comandi ufficiale (pulsante "Menu" blu della chat).
COMANDI = [
    ("start", "Avvia e mostra il menu"),
    ("menu", "Mostra il menu a pulsanti"),
    ("task", "Crea un task per te"),
    ("cerca", "Cerca clienti e pratiche"),
    ("collega", "Collega il tuo account (codice)"),
    ("aiuto", "Come si usa il bot"),
]


def set_commands():
    return _api("setMyCommands",
                {"commands": [{"command": c, "description": d} for c, d in COMANDI]})


def delete_webhook():
    return _api("deleteWebhook", {})


# ── Utility ──────────────────────────────────────────────────────────────────
def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _url(path):
    return f"{BASE_URL}{path}" if BASE_URL else path


def _esc(s):
    s = str(s or "")
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Stato conversazionale (tabella telegram_pending) ─────────────────────────
def set_pending(chat_id, azione, ref_id=None, extra=None):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM telegram_pending WHERE chat_id = {_PH}", (str(chat_id),))
        cur.execute(
            f"INSERT INTO telegram_pending (chat_id, azione, ref_id, extra) "
            f"VALUES ({_PH}, {_PH}, {_PH}, {_PH})",
            (str(chat_id), azione, ref_id, extra),
        )


def get_pending(chat_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT azione, ref_id, extra FROM telegram_pending WHERE chat_id = {_PH}",
            (str(chat_id),))
        row = cur.fetchone()
        return dict(row) if row else None


def clear_pending(chat_id):
    with get_db() as conn:
        conn.cursor().execute(
            f"DELETE FROM telegram_pending WHERE chat_id = {_PH}", (str(chat_id),))


# ── Ricerca ──────────────────────────────────────────────────────────────────
def _tokens(q):
    return [t for t in re.split(r"\s+", (q or "").strip()) if t]


def cerca_clienti(q, limit=6):
    toks = _tokens(q)
    if not toks:
        return []
    where, params = [], []
    for t in toks:
        like = f"%{t}%"
        where.append(f"(cognome {_LIKE} {_PH} OR nome {_LIKE} {_PH} OR codice_fiscale {_LIKE} {_PH})")
        params += [like, like, like]
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, cognome, nome, asl FROM clienti WHERE {' AND '.join(where)} "
            f"ORDER BY cognome, nome LIMIT {int(limit)}", tuple(params))
        return [dict(r) for r in cur.fetchall()]


def cerca_pratiche(q, limit=6):
    toks = _tokens(q)
    if not toks:
        return []
    where, params = [], []
    for t in toks:
        like = f"%{t}%"
        where.append(
            f"(p.nome_paziente {_LIKE} {_PH} OR c.cognome {_LIKE} {_PH} OR c.nome {_LIKE} {_PH} "
            f"OR p.numero_pratica {_LIKE} {_PH})")
        params += [like, like, like, like]
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT p.id, p.nome_paziente, p.numero_pratica, p.stato_lavorazione,
                       p.fatturata, c.cognome, c.nome
                FROM pratiche p LEFT JOIN clienti c ON c.id = p.cliente_id
                WHERE {' AND '.join(where)}
                ORDER BY p.data_pratica DESC, p.id DESC LIMIT {int(limit)}""",
            tuple(params))
        return [dict(r) for r in cur.fetchall()]


def _nome_pratica(p):
    if p.get("cognome"):
        return f"{p['cognome']} {p.get('nome') or ''}".strip()
    return p.get("nome_paziente") or "—"


# ── Scheda pratica + azioni ──────────────────────────────────────────────────
def scheda_pratica(pratica_id):
    """(testo, righe_bottoni) per una pratica, o (None, None) se assente."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT p.*, c.cognome, c.nome,
                       COALESCE((SELECT SUM(importo) FROM preventivi WHERE pratica_id = p.id), 0) AS costo
                FROM pratiche p LEFT JOIN clienti c ON c.id = p.cliente_id
                WHERE p.id = {_PH}""", (pratica_id,))
        row = cur.fetchone()
    if not row:
        return None, None
    p = dict(row)
    nome = _nome_pratica(p)
    stato = p.get("stato_lavorazione") or "Da valutare"
    asl = p.get("importo_asl") or 0
    priv = p.get("importo_privato") or 0
    costo = p.get("costo") or 0
    ricavi = asl + priv
    prov = p.get("provvigione_pct") or 0.16
    mol = ricavi - costo - ricavi * prov - ricavi * 0.10
    marg = (mol / ricavi * 100) if ricavi else 0
    fatt = "✅ Fatturata" if p.get("fatturata") else ""
    testo = (f"📁 <b>{_esc(nome)}</b>  {fatt}\n"
             f"Stato: <b>{_esc(stato)}</b>\n"
             f"ASL € {ricavi:,.0f} · costo € {costo:,.0f} · <b>margine {marg:.0f}%</b>")

    rows = []
    prossimo = _prossimo_stato(stato)
    if not p.get("fatturata"):
        avanti = []
        if prossimo:
            avanti.append((f"➡️ {prossimo}", {"cb": f"adv:{pratica_id}"}))
        avanti.append(("🔄 Stato", {"cb": f"st:{pratica_id}"}))
        rows.append(avanti)
        rows.append([("🧾 Fatturata", {"cb": f"fat:{pratica_id}"})])
    rows.append([("➕ Task", {"cb": f"tk:{pratica_id}"}),
                 ("🔗 Apri", {"url": _url(f"/pratica/{pratica_id}")})])
    return testo, rows


def _prossimo_stato(stato):
    try:
        i = STATI_LAVORAZIONE.index(stato)
    except ValueError:
        i = 0
    return STATI_LAVORAZIONE[i + 1] if i + 1 < len(STATI_LAVORAZIONE) else None


def avanza_stato(pratica_id):
    """Porta la pratica allo stato successivo. Restituisce il nuovo stato o None."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT stato_lavorazione, fatturata FROM pratiche WHERE id = {_PH}",
                    (pratica_id,))
        row = cur.fetchone()
        if not row or row["fatturata"]:
            return None
        nuovo = _prossimo_stato(row["stato_lavorazione"] or "Da valutare")
        if not nuovo:
            return None
        if nuovo == "Fatturato":
            return set_fatturato(pratica_id)
        cur.execute(
            f"UPDATE pratiche SET stato_lavorazione = {_PH}, stato_da = {_PH} WHERE id = {_PH}",
            (nuovo, _now_iso(), pratica_id))
        return nuovo


def imposta_stato(pratica_id, stato):
    """Imposta DIRETTAMENTE lo stato scelto (senza rispettare la sequenza).
    'Fatturato' passa da set_fatturato. Ritorna lo stato o None se non valido."""
    if stato not in STATI_LAVORAZIONE:
        return None
    if stato == "Fatturato":
        return set_fatturato(pratica_id)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT id FROM pratiche WHERE id = {_PH}", (pratica_id,))
        if not cur.fetchone():
            return None
        cur.execute(
            f"UPDATE pratiche SET stato_lavorazione = {_PH}, stato_da = {_PH} WHERE id = {_PH}",
            (stato, _now_iso(), pratica_id))
    return stato


def _tastiera_stati(pratica_id):
    """Righe di bottoni per scegliere direttamente uno stato (escluso Fatturato,
    che ha il pulsante 🧾 dedicato). Usa l'indice dello stato nel callback."""
    rows, fila = [], []
    for i, s in enumerate(STATI_LAVORAZIONE):
        if s == "Fatturato":
            continue
        fila.append((s, {"cb": f"sts:{pratica_id}:{i}"}))
        if len(fila) == 2:
            rows.append(fila); fila = []
    if fila:
        rows.append(fila)
    rows.append([("⬅️ Indietro", {"cb": f"p:{pratica_id}"})])
    return rows


def set_fatturato(pratica_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE pratiche SET fatturata = {_PH}, data_fatturazione = {_PH}, "
            f"stato_lavorazione = {_PH}, stato_da = {_PH} WHERE id = {_PH}",
            (True, date.today().isoformat(), "Fatturato", _now_iso(), pratica_id))
    return "Fatturato"


# ── Task / note ──────────────────────────────────────────────────────────────
def crea_task(testo, autore_id, assegnatari=None, cliente_id=None,
              nominativo="", priorita="Media", notifica=True):
    """Crea un task (riga note). Restituisce l'id. Se `notifica`, avvisa via
    Telegram gli assegnatari collegati (diversi dall'autore)."""
    assegnatari = [int(a) for a in (assegnatari or [])]
    scadenza = None
    giorni = NOTE_PRIORITA_GIORNI.get(priorita)
    if giorni:
        scadenza = (date.today() + timedelta(days=giorni)).isoformat()
    assegnato_a = assegnatari[0] if assegnatari else None
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""INSERT INTO note (cliente_id, nominativo, tipo, sottotipo, priorita,
                    stato, completata, testo, scadenza, autore_id, assegnato_a)
                VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})""",
            (cliente_id, nominativo or "", "Assistenza", "", priorita, "Aperta",
             False, testo, scadenza, autore_id, assegnato_a))
        nota_id = last_inserted_id(cur)
        for uid in assegnatari:
            cur.execute(
                f"INSERT INTO note_assegnatari (note_id, utente_id) VALUES ({_PH}, {_PH})",
                (nota_id, uid))
    if notifica and assegnatari:
        autore_nome = _nome_utente(autore_id) if autore_id else "qualcuno"
        notify_task_assegnato(assegnatari, testo, autore_nome, escludi=autore_id)
    return nota_id


def _nome_utente(utente_id):
    if not utente_id:
        return None
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT nome FROM utenti WHERE id = {_PH}", (int(utente_id),))
        row = cur.fetchone()
        return row["nome"] if row else None


def notify_task_assegnato(assegnatari_ids, testo, autore_nome, escludi=None):
    """Avvisa su Telegram gli utenti assegnati (se collegati), tranne `escludi`."""
    if not attivo():
        return
    for uid in assegnatari_ids:
        if escludi and int(uid) == int(escludi):
            continue
        chat = chat_id_utente(uid)
        if chat:
            send_message(
                chat,
                f"🔔 <b>Nuovo task per te</b>\n{_esc(testo)}\n<i>da {_esc(autore_nome)}</i>")


def trova_utenti_per_nome(nome, limit=5):
    like = f"%{(nome or '').strip()}%"
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, nome FROM utenti WHERE attivo AND nome {_LIKE} {_PH} "
            f"ORDER BY nome LIMIT {int(limit)}", (like,))
        return [dict(r) for r in cur.fetchall()]


# ── Menu a pulsanti (tastiera persistente) ───────────────────────────────────
BTN_CERCA      = "🔎 Cerca"
BTN_MIEI       = "📋 I miei task"
BTN_TASK_ME    = "✅ Task a me"
BTN_TASK_ALTRO = "👥 Task a un collega"
BTN_RIEPILOGO  = "🌅 Riepilogo"
BTN_AIUTO      = "❓ Aiuto"
MENU_LABELS = {BTN_CERCA, BTN_MIEI, BTN_TASK_ME, BTN_TASK_ALTRO, BTN_RIEPILOGO, BTN_AIUTO}


def _menu_markup():
    """Tastiera persistente sempre disponibile in fondo alla chat."""
    return {
        "keyboard": [
            [{"text": BTN_CERCA}, {"text": BTN_MIEI}],
            [{"text": BTN_TASK_ME}, {"text": BTN_TASK_ALTRO}],
            [{"text": BTN_RIEPILOGO}, {"text": BTN_AIUTO}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Scrivi un nome o usa i pulsanti…",
    }


def send_menu(chat_id, text):
    return send_message(chat_id, text, reply_markup=_menu_markup())


# ── Dispatcher principale ────────────────────────────────────────────────────
AIUTO = (
    "🤖 <b>Gestionale — come si usa</b>\n"
    "Usa i <b>pulsanti</b> in basso, oppure scrivi:\n"
    "• un <b>nome</b> → cerca clienti e pratiche;\n"
    "• <code>/task testo</code> → task per te;\n"
    "• <code>avvisa NOME di testo</code> → task a un collega, con avviso.\n\n"
    "Dai risultati apri una pratica e usa i pulsanti "
    "<b>➡️ stato</b>, <b>🧾 Fatturata</b>, <b>➕ Task</b>."
)


def handle_update(update: dict):
    try:
        if "callback_query" in update:
            _handle_callback(update["callback_query"])
        elif "message" in update:
            _handle_message(update["message"])
    except Exception:
        # Non far mai fallire il webhook: Telegram ritenterebbe all'infinito.
        pass


def _handle_message(msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text:
        return
    low = text.lower()

    # Comandi che NON richiedono di essere già collegati
    if low.startswith("/start"):
        u = get_utente_by_chat_id(chat_id)
        if u:
            send_menu(chat_id, f"Ciao {_esc(u['nome'])}! 👋\n\n{AIUTO}")
        else:
            send_message(chat_id,
                "👋 Benvenuto nel bot del gestionale.\n"
                "Per usarlo collega il tuo account: apri <b>Gestione utenti</b> "
                "nell'app, genera il codice e scrivimi:\n<code>/collega IL_TUO_CODICE</code>")
        return
    if low.startswith("/collega"):
        parti = text.split(maxsplit=1)
        codice = parti[1].strip() if len(parti) > 1 else ""
        u = collega_telegram(codice, chat_id)
        if u:
            send_menu(chat_id, f"✅ Collegato come <b>{_esc(u['nome'])}</b>.\n\n{AIUTO}")
        else:
            send_message(chat_id, "❌ Codice non valido o scaduto. Rigeneralo in Gestione utenti.")
        return

    # Da qui in poi serve essere collegati
    u = get_utente_by_chat_id(chat_id)
    if not u:
        send_message(chat_id,
            "🔒 Non sei collegato. Genera il codice in <b>Gestione utenti</b> e invia "
            "<code>/collega CODICE</code>.")
        return

    if low in ("/aiuto", "/help", "/menu"):
        send_menu(chat_id, AIUTO)
        return

    # Pulsanti del menu (tastiera persistente): hanno priorità e annullano l'attesa
    if text in MENU_LABELS:
        clear_pending(chat_id)
        _menu_azione(chat_id, u, text)
        return

    # C'è un'azione in sospeso? (es. attesa del testo di un task)
    pend = get_pending(chat_id)
    if pend and not text.startswith("/"):
        _consuma_pending(chat_id, u, pend, text)
        return

    # "avvisa NOME di/che TESTO"
    m = re.match(r"^avvisa\s+(.+?)\s+(?:di|che|:)\s+(.+)$", text, re.IGNORECASE)
    if m:
        _avvisa_collega(chat_id, u, m.group(1).strip(), m.group(2).strip())
        return

    if low.startswith("/task"):
        parti = text.split(maxsplit=1)
        if len(parti) > 1:
            crea_task(parti[1].strip(), autore_id=u["id"], assegnatari=[u["id"]], notifica=False)
            send_message(chat_id, "✅ Task creato (assegnato a te).")
        else:
            send_message(chat_id, "Scrivi il testo: <code>/task richiamare il fornitore</code>")
        return

    if low.startswith("/cerca"):
        parti = text.split(maxsplit=1)
        text = parti[1].strip() if len(parti) > 1 else ""
        if not text:
            send_message(chat_id, "Scrivi cosa cercare: <code>/cerca Rossi</code>")
            return

    # Default: ricerca
    _rispondi_ricerca(chat_id, text)


def _rispondi_ricerca(chat_id, q):
    cli = cerca_clienti(q)
    pra = cerca_pratiche(q)
    if not cli and not pra:
        send_message(chat_id, f"Nessun risultato per «{_esc(q)}».")
        return
    rows = []
    for c in cli:
        nome = f"{c['cognome']} {c.get('nome') or ''}".strip()
        rows.append([(f"👤 {nome}" + (f" · {c['asl']}" if c.get('asl') else ""),
                      {"cb": f"c:{c['id']}"})])
    for p in pra:
        stato = p.get("stato_lavorazione") or ""
        flag = "🧾" if p.get("fatturata") else "📁"
        rows.append([(f"{flag} {_nome_pratica(p)} · {stato}", {"cb": f"p:{p['id']}"})])
    send_message(chat_id, f"Risultati per «{_esc(q)}»:", rows)


def _consuma_pending(chat_id, u, pend, text):
    azione = pend["azione"]
    clear_pending(chat_id)
    if azione == "cerca":
        _rispondi_ricerca(chat_id, text)
    elif azione == "task_self":
        crea_task(text, autore_id=u["id"], assegnatari=[u["id"]], notifica=False)
        send_menu(chat_id, "✅ Task creato (assegnato a te).")
    elif azione == "task_altro":
        dest_id = int(pend["ref_id"])
        crea_task(text, autore_id=u["id"], assegnatari=[dest_id], notifica=True)
        send_menu(chat_id, f"✅ Task assegnato a <b>{_esc(_nome_utente(dest_id))}</b> e avvisato.")
    elif azione == "task_pratica":
        pratica_id = pend["ref_id"]
        cliente_id = _cliente_di_pratica(pratica_id)
        crea_task(text, autore_id=u["id"], assegnatari=[u["id"]],
                  cliente_id=cliente_id, notifica=False)
        send_message(chat_id, "✅ Task aggiunto alla pratica (assegnato a te).",
                     [[("🔗 Apri pratica", {"url": _url(f"/pratica/{pratica_id}")})]])
    else:
        send_message(chat_id, "Ok.")


# ── Azioni del menu a pulsanti ───────────────────────────────────────────────
def _menu_azione(chat_id, u, label):
    if label == BTN_CERCA:
        set_pending(chat_id, "cerca")
        send_message(chat_id, "🔎 Scrivi cosa cercare (nome, cognome o n° pratica):")
    elif label == BTN_TASK_ME:
        set_pending(chat_id, "task_self")
        send_message(chat_id, "✅ Scrivi il testo del task (verrà assegnato a te):")
    elif label == BTN_TASK_ALTRO:
        _scegli_collega(chat_id, u)
    elif label == BTN_MIEI:
        _miei_task(chat_id, u)
    elif label == BTN_RIEPILOGO:
        _riepilogo(chat_id, u)
    elif label == BTN_AIUTO:
        send_menu(chat_id, AIUTO)


def _scegli_collega(chat_id, u):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, nome FROM utenti WHERE attivo AND id <> {_PH} ORDER BY nome",
            (u["id"],))
        altri = [dict(r) for r in cur.fetchall()]
    if not altri:
        send_message(chat_id, "Non ci sono altri utenti a cui assegnare un task.")
        return
    rows = [[(a["nome"], {"cb": f"nt:{a['id']}"})] for a in altri]
    send_message(chat_id, "👥 A chi assegno il task?", rows)


def _miei_task(chat_id, u):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT n.id, n.testo, n.scadenza FROM note n
                JOIN note_assegnatari na ON na.note_id = n.id
                WHERE na.utente_id = {_PH} AND NOT n.completata
                ORDER BY COALESCE(n.scadenza, '9999-12-31') ASC, n.id DESC LIMIT 15""",
            (u["id"],))
        task = [dict(r) for r in cur.fetchall()]
    if not task:
        send_message(chat_id, "🎉 Non hai task aperti.")
        return
    send_message(chat_id, f"📋 <b>I tuoi task aperti</b> ({len(task)}):")
    for t in task:
        scad = f"  <i>⏰ {t['scadenza']}</i>" if t.get("scadenza") else ""
        rows = [[("✓ Fatto", {"cb": f"done:{t['id']}"}),
                 ("🗑 Elimina", {"cb": f"del:{t['id']}"})]]
        send_message(chat_id, f"• {_esc(t['testo'])}{scad}", rows)


def _riepilogo(chat_id, u):
    res = _costruisci_digest(u["id"])
    if not res:
        send_message(chat_id, "✅ Nulla in scadenza e nessuna pratica ferma. Tutto in ordine!")
        return
    testo, rows = res
    send_message(chat_id, testo, rows)


def _completa_task(note_id):
    with get_db() as conn:
        conn.cursor().execute(
            f"UPDATE note SET completata = {_PH}, stato = {_PH} WHERE id = {_PH}",
            (True, "Completata", note_id))


def _elimina_task(note_id):
    with get_db() as conn:
        conn.cursor().execute(f"DELETE FROM note WHERE id = {_PH}", (note_id,))


def _avvisa_collega(chat_id, u, nome, testo):
    cand = trova_utenti_per_nome(nome)
    if not cand:
        send_message(chat_id, f"Nessun utente trovato per «{_esc(nome)}».")
        return
    if len(cand) == 1:
        dest = cand[0]
        crea_task(testo, autore_id=u["id"], assegnatari=[dest["id"]], notifica=True)
        send_message(chat_id, f"✅ Task assegnato a <b>{_esc(dest['nome'])}</b> e avvisato.")
        return
    # più candidati → memorizza il testo e chiedi a chi assegnare
    set_pending(chat_id, "avvisa_scegli", extra=testo)
    rows = [[(c["nome"], {"cb": f"avv:{c['id']}"})] for c in cand]
    send_message(chat_id, "A chi lo assegno?", rows)


def _handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    cb_id = cb["id"]
    data = cb.get("data") or ""

    u = get_utente_by_chat_id(chat_id)
    if not u:
        answer_callback(cb_id, "Non sei collegato.")
        return

    if ":" not in data:
        answer_callback(cb_id)
        return
    tipo, _, arg = data.partition(":")

    if tipo == "p":
        testo, rows = scheda_pratica(int(arg))
        answer_callback(cb_id)
        if testo:
            edit_message(chat_id, message_id, testo, rows)
        return
    if tipo == "c":
        _scheda_cliente(chat_id, int(arg))
        answer_callback(cb_id)
        return
    if tipo == "adv":
        nuovo = avanza_stato(int(arg))
        answer_callback(cb_id, f"Stato: {nuovo}" if nuovo else "Non modificabile")
        testo, rows = scheda_pratica(int(arg))
        if testo:
            edit_message(chat_id, message_id, testo, rows)
        return
    if tipo == "st":  # mostra la tastiera per scegliere direttamente lo stato
        pid = int(arg)
        testo, _ = scheda_pratica(pid)
        answer_callback(cb_id)
        if testo:
            edit_message(chat_id, message_id, testo + "\n\n<i>Scegli il nuovo stato:</i>",
                         _tastiera_stati(pid))
        return
    if tipo == "sts":  # imposta direttamente lo stato scelto (arg = "<pid>:<indice>")
        pid_s, _, idx_s = arg.partition(":")
        stato = None
        try:
            stato = STATI_LAVORAZIONE[int(idx_s)]
        except (ValueError, IndexError):
            stato = None
        nuovo = imposta_stato(int(pid_s), stato) if stato else None
        answer_callback(cb_id, f"Stato: {nuovo}" if nuovo else "Non valido")
        testo, rows = scheda_pratica(int(pid_s))
        if testo:
            edit_message(chat_id, message_id, testo, rows)
        return
    if tipo == "fat":
        set_fatturato(int(arg))
        answer_callback(cb_id, "Segnata Fatturata")
        testo, rows = scheda_pratica(int(arg))
        if testo:
            edit_message(chat_id, message_id, testo, rows)
        return
    if tipo == "tk":
        set_pending(chat_id, "task_pratica", ref_id=int(arg))
        answer_callback(cb_id)
        send_message(chat_id, "✍️ Scrivi il testo del task per questa pratica:")
        return
    if tipo == "nt":  # nuovo task per un collega scelto dal menu
        set_pending(chat_id, "task_altro", ref_id=int(arg))
        answer_callback(cb_id)
        send_message(chat_id, f"✍️ Scrivi il testo del task per <b>{_esc(_nome_utente(int(arg)))}</b>:")
        return
    if tipo == "done":  # segna un task come fatto (dalla lista "I miei task")
        _completa_task(int(arg))
        answer_callback(cb_id, "Fatto ✓")
        edit_message(chat_id, message_id, "✅ <s>task completato</s>")
        return
    if tipo == "del":  # elimina un task
        _elimina_task(int(arg))
        answer_callback(cb_id, "Eliminato")
        edit_message(chat_id, message_id, "🗑 <i>task eliminato</i>")
        return
    if tipo == "avv":
        pend = get_pending(chat_id)
        testo = (pend or {}).get("extra") if pend else None
        clear_pending(chat_id)
        if testo:
            crea_task(testo, autore_id=u["id"], assegnatari=[int(arg)], notifica=True)
            nome = _nome_utente(int(arg))
            answer_callback(cb_id, "Assegnato")
            send_message(chat_id, f"✅ Task assegnato a <b>{_esc(nome)}</b> e avvisato.")
        else:
            answer_callback(cb_id, "Scaduto, riprova")
        return
    answer_callback(cb_id)


def _scheda_cliente(chat_id, cliente_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, cognome, nome, asl, telefono, residenza_via FROM clienti WHERE id = {_PH}",
            (cliente_id,))
        row = cur.fetchone()
        if not row:
            send_message(chat_id, "Cliente non trovato.")
            return
        c = dict(row)
        cur.execute(
            f"""SELECT id, nome_paziente, numero_pratica, stato_lavorazione, fatturata
                FROM pratiche WHERE cliente_id = {_PH}
                ORDER BY data_pratica DESC, id DESC LIMIT 6""", (cliente_id,))
        prat = [dict(r) for r in cur.fetchall()]
    nome = f"{c['cognome']} {c.get('nome') or ''}".strip()
    righe = [f"👤 <b>{_esc(nome)}</b>"]
    if c.get("asl"):
        righe.append(f"ASL {_esc(c['asl'])}")
    if c.get("telefono"):
        righe.append(f"📞 {_esc(c['telefono'])}")
    rows = []
    for p in prat:
        stato = p.get("stato_lavorazione") or ""
        flag = "🧾" if p.get("fatturata") else "📁"
        rows.append([(f"{flag} pratica · {stato}", {"cb": f"p:{p['id']}"})])
    rows.append([("🔗 Apri cliente", {"url": _url(f"/cliente/{cliente_id}")})])
    send_message(chat_id, "\n".join(righe), rows)


def _cliente_di_pratica(pratica_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT cliente_id FROM pratiche WHERE id = {_PH}", (pratica_id,))
        row = cur.fetchone()
        return row["cliente_id"] if row else None


# ── Digest / riepilogo ───────────────────────────────────────────────────────
def _giorni_fermo(ts):
    """Giorni interi da `ts` (stato_da) a oggi, o None."""
    if not ts:
        return None
    try:
        dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts).replace(" ", "T"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return max((datetime.now() - dt).days, 0)


def _pratiche_ferme(limite=15, giorni=PRATICHE_FERME_GIORNI):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT p.id, p.nome_paziente, p.stato_lavorazione, p.stato_da,
                       c.cognome, c.nome
                FROM pratiche p LEFT JOIN clienti c ON c.id = p.cliente_id
                WHERE p.fatturata <> {_FATTURATA_TRUE} AND p.stato_da IS NOT NULL
                  AND p.stato_da <= {_PH}
                ORDER BY p.stato_da ASC LIMIT {int(limite)}""",
            ((datetime.now() - timedelta(days=int(giorni))).isoformat(),))
        righe = [dict(r) for r in cur.fetchall()]
    for r in righe:
        r["giorni_fermo"] = _giorni_fermo(r.get("stato_da"))
    return righe


def _costruisci_digest(utente_id, ferme=None):
    """(testo, righe_bottoni) del riepilogo per un utente, o None se non c'è nulla."""
    if ferme is None:
        ferme = _pratiche_ferme()
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT n.testo, n.scadenza FROM note n
                JOIN note_assegnatari na ON na.note_id = n.id
                WHERE na.utente_id = {_PH} AND NOT n.completata
                  AND n.scadenza IS NOT NULL AND n.scadenza <= {_PH}
                ORDER BY n.scadenza ASC LIMIT 10""",
            (utente_id, (date.today() + timedelta(days=3)).isoformat()))
        task = [dict(r) for r in cur.fetchall()]
    if not ferme and not task:
        return None
    parti = ["🌅 <b>Riepilogo</b>"]
    if task:
        parti.append("\n<b>I tuoi task in scadenza:</b>")
        for t in task:
            parti.append(f"• {_esc(t['testo'])} <i>({t['scadenza']})</i>")
    if ferme:
        parti.append(f"\n<b>Pratiche ferme da &ge;{PRATICHE_FERME_GIORNI} giorni:</b>")
        for p in ferme[:10]:
            gg = p.get("giorni_fermo")
            suffisso = f" · <i>da {gg} gg</i>" if gg is not None else ""
            parti.append(f"• {_esc(_nome_pratica(p))} — {_esc(p.get('stato_lavorazione') or '')}{suffisso}")
    rows = [[("📋 Apri i task", {"url": _url("/task-assegnati")})]]
    return "\n".join(parti), rows


def invia_digest():
    """Manda a ogni utente collegato i suoi task in scadenza (ogni giorno) e, una
    volta a settimana, le pratiche ferme da ≥N giorni. Pensata per una chiamata al
    giorno (cron/UptimeRobot): la sezione "ferme" compare solo nel giorno stabilito
    (PRATICHE_FERME_GIORNO_SETTIMANA), così il promemoria è settimanale."""
    if not attivo():
        return {"inviati": 0}
    inviati = 0
    # Le pratiche ferme entrano nel digest solo nel giorno settimanale scelto;
    # negli altri giorni si mandano solo i task in scadenza.
    if datetime.now().weekday() == PRATICHE_FERME_GIORNO_SETTIMANA:
        ferme = _pratiche_ferme()
    else:
        ferme = []
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, telegram_chat_id FROM utenti "
                    "WHERE attivo AND telegram_chat_id IS NOT NULL")
        utenti = [dict(r) for r in cur.fetchall()]
    for u in utenti:
        res = _costruisci_digest(u["id"], ferme=ferme)
        if not res:
            continue
        testo, rows = res
        if send_message(u["telegram_chat_id"], testo, rows):
            inviati += 1
    return {"inviati": inviati}
