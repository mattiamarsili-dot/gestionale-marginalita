import calendar
import json
import os
from datetime import datetime, date
from flask import (
    Flask, render_template, request, redirect,
    url_for, jsonify, session, Response,
)
from werkzeug.utils import secure_filename

from config import (
    SECRET_KEY, ACCESS_CODE,
    UPLOAD_FOLDER, MAX_UPLOAD_MB,
    PROVVIGIONE_PCT, PROVVIGIONE_PCT_RIDOTTA, STRUTTURA_PCT,
    PROVVIGIONE_PCT_17, PROVVIGIONE_PCT_18, SOGLIA_PROV_17, SOGLIA_PROV_18,
    MARGINE_SOGLIA_OK, MARGINE_SOGLIA_WARN, CENTRI, ASL_OPZIONI,
    ANTHROPIC_API_KEY,
)
from database import (
    init_db, migrate_db, backfill_clienti, get_db, calcola_margine, provvigione_corrente,
    _PH, _DATE_FILTER, _MONTH_FORMAT, _FATTURATA_TRUE, last_inserted_id,
)
from pdf_extractor import estrai_totale_pdf
from drive_sync import drive_configurato
from pdf_filler import (
    PDF_TEMPLATES, MODULI_SEMPRE_ATTIVI, moduli_ordinati,
    compila_pdf, nome_file_consigliato, numero_preventivo,
)
from presets import (
    seed_presets, preset_per_categoria, get_preset, lista_preset,
    crea_preset, aggiorna_preset, elimina_preset, categorie_note,
    significato_per_categoria,
    seed_significato_catalogo, significato_catalogo, SIGNIFICATO_ARTICOLI,
    aggiungi_motivazione, aggiorna_motivazione, elimina_motivazione,
)

# ── Periodi predefiniti ────────────────────────────────────────────────────────

_DURATA_MESI = {
    "mensile": 1,
    "bimestrale": 2,
    "trimestrale": 3,
    "semestrale": 6,
    "annuale": 12,
}


def _calcola_range(da_str: str, periodo: str) -> tuple[str, str]:
    """Restituisce (data_da_str, data_al_str) YYYY-MM-DD per il periodo scelto."""
    try:
        anno, m = (int(x) for x in da_str.split("-"))
    except Exception:
        today = date.today()
        anno, m = today.year, today.month

    mesi = _DURATA_MESI.get(periodo, 1)
    m0 = m - 1                          # 0-based
    end_m0 = m0 + mesi - 1
    mese_al = end_m0 % 12 + 1
    anno_al = anno + end_m0 // 12
    gg_al = calendar.monthrange(anno_al, mese_al)[1]

    return (
        f"{anno:04d}-{m:02d}-01",
        f"{anno_al:04d}-{mese_al:02d}-{gg_al:02d}",
    )

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Inizializza DB all'avvio (funziona sia con `python app.py` che con gunicorn)
try:
    init_db()
    migrate_db()
    backfill_clienti()
    seed_presets()
    seed_significato_catalogo()
except Exception as _db_err:
    import sys, traceback
    print("ERRORE AVVIO DB:", _db_err, file=sys.stderr)
    traceback.print_exc(file=sys.stderr)

ALLOWED_EXTENSIONS = {"pdf"}


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Autenticazione ────────────────────────────────────────────────────────────

ROUTE_PUBBLICHE = {"login", "logout", "static", "manifest", "service_worker",
                   "modulo_paziente"}

@app.before_request
def controlla_accesso():
    if not ACCESS_CODE:
        return None
    if request.endpoint in ROUTE_PUBBLICHE:
        return None
    if not session.get("autenticato"):
        return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    errore = None
    if request.method == "POST":
        codice = request.form.get("codice", "").strip()
        if codice == ACCESS_CODE:
            session["autenticato"] = True
            session.permanent = True
            return redirect(url_for("dashboard"))
        errore = "Codice non valido. Riprova."
    return render_template("login.html", errore=errore)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── PWA: manifest + service worker (app installabile su telefono/tablet) ──────

@app.route("/manifest.webmanifest")
def manifest():
    import json
    data = {
        "name": "Gestionale Marginalità",
        "short_name": "Gestionale",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#0d6efd",
        "icons": [
            {"src": url_for("static", filename="icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": url_for("static", filename="icons/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return Response(json.dumps(data), mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    # Service worker minimale: cache dei soli asset statici (no pagine autenticate),
    # sufficiente a rendere l'app installabile. Servito da root per avere scope "/".
    js = """
const CACHE = 'gm-v1';
const ASSETS = [
  '/static/style.css', '/static/select-add.js',
  '/static/icons/icon-192.png', '/static/icons/icon-512.png',
  '/manifest.webmanifest',
];
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.webmanifest') {
    e.respondWith(caches.match(req).then((r) => r || fetch(req)));
  }
});
"""
    resp = Response(js, mimetype="text/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    periodo = request.args.get("periodo", "mensile")
    if periodo not in _DURATA_MESI:
        periodo = "mensile"

    # Retrocompatibilità con il vecchio parametro ?mese=
    da = request.args.get("da") or request.args.get("mese", datetime.now().strftime("%Y-%m"))

    data_da, data_al = _calcola_range(da, periodo)

    sql = f"""
        SELECT p.*,
               COALESCE(SUM(pr.importo), 0) AS costo_totale
        FROM pratiche p
        LEFT JOIN preventivi pr ON pr.pratica_id = p.id
        WHERE p.data_pratica >= {_PH} AND p.data_pratica <= {_PH}
        GROUP BY p.id
        ORDER BY p.data_pratica DESC
    """

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(sql, (data_da, data_al))
        pratiche = cur.fetchall()

        cur.execute(
            f"SELECT DISTINCT {_MONTH_FORMAT} AS ym "
            "FROM pratiche ORDER BY ym DESC LIMIT 36"
        )
        mesi_disponibili = [r["ym"] for r in cur.fetchall()]

        # Widget dashboard: ultime pratiche, note in sospeso, ultimi clienti.
        cur.execute(
            """SELECT id, nome_paziente, cliente_id, data_pratica, importo_asl,
                      fatturata, creato_il
               FROM pratiche
               ORDER BY creato_il DESC, id DESC LIMIT 6"""
        )
        ultime_pratiche = cur.fetchall()

        cur.execute("SELECT COUNT(*) AS n FROM note WHERE NOT completata")
        note_sospese = cur.fetchone()["n"]

        cur.execute(
            """SELECT id, cognome, nome, centro, creato_il
               FROM clienti
               ORDER BY creato_il DESC, id DESC LIMIT 5"""
        )
        ultimi_clienti = cur.fetchall()

    if da not in mesi_disponibili:
        mesi_disponibili.insert(0, da)

    stats = {
        "num_pratiche": 0,
        "totale_ricavi": 0.0,
        "media_margine": 0.0,
        "mol_totale": 0.0,
        "totale_provvigioni": 0.0,
    }
    righe = []

    for pr in pratiche:
        m_dati = calcola_margine(pr["importo_asl"], pr["costo_totale"], pr["provvigione_pct"], pr["importo_privato"] or 0)
        stats["num_pratiche"]        += 1
        stats["totale_ricavi"]       += m_dati["ricavi_totali"]
        stats["mol_totale"]          += m_dati["mol"]
        stats["totale_provvigioni"]  += m_dati["provvigione"]
        righe.append({**dict(pr), **m_dati})

    if stats["totale_ricavi"] > 0:
        stats["media_margine"] = stats["mol_totale"] / stats["totale_ricavi"] * 100

    # Totale annuo fatturato (gen-dic anno corrente) per soglie provvigione
    with get_db() as conn:
        fatturato_annuo_asl, prov_corrente = provvigione_corrente(conn)

    return render_template(
        "dashboard.html",
        pratiche=righe,
        stats=stats,
        da_sel=da,
        periodo_sel=periodo,
        periodi=list(_DURATA_MESI.keys()),
        mesi_disponibili=mesi_disponibili,
        soglia_ok=MARGINE_SOGLIA_OK,
        soglia_warn=MARGINE_SOGLIA_WARN,
        drive_attivo=drive_configurato(),
        provvigione_std=PROVVIGIONE_PCT * 100,
        provvigione_rid=PROVVIGIONE_PCT_RIDOTTA * 100,
        fatturato_annuo_asl=fatturato_annuo_asl,
        prov_corrente=prov_corrente * 100,
        soglia_17=SOGLIA_PROV_17,
        soglia_18=SOGLIA_PROV_18,
        ultime_pratiche=ultime_pratiche,
        note_sospese=note_sospese,
        ultimi_clienti=ultimi_clienti,
    )


# ── Nuova pratica ─────────────────────────────────────────────────────────────

@app.route("/nuova", methods=["GET", "POST"])
def nuova_pratica():
    if request.method == "POST":
        nome_paziente = request.form["nome_paziente"].strip()
        cliente_id    = request.form.get("cliente_id") or None
        data_pratica  = request.form["data_pratica"]
        # Bozza: l'importo ASL si compila nella scheda Marginalità (default 0)
        importo_asl     = float(request.form.get("importo_asl") or 0)
        importo_privato = float(request.form.get("importo_privato") or 0)
        note            = request.form.get("note", "").strip()

        provvigione_pct = float(request.form.get("provvigione_pct", PROVVIGIONE_PCT))
        fornitori  = request.form.getlist("fornitore_nome[]")
        importi    = request.form.getlist("fornitore_importo[]")
        file_pdfs  = request.form.getlist("fornitore_pdf[]")
        drive_ids  = request.form.getlist("fornitore_drive_id[]")

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO pratiche (nome_paziente, cliente_id, data_pratica, importo_asl, importo_privato, provvigione_pct, note) "
                f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
                (nome_paziente, cliente_id, data_pratica, importo_asl, importo_privato, provvigione_pct, note),
            )
            pratica_id = last_inserted_id(cur)

            for i, (nome_f, imp_f) in enumerate(zip(fornitori, importi)):
                nome_f = nome_f.strip()
                if not nome_f or not imp_f:
                    continue
                pdf_path  = file_pdfs[i]  if i < len(file_pdfs)  else None
                drive_id  = drive_ids[i]  if i < len(drive_ids)  else None
                cur.execute(
                    f"INSERT INTO preventivi "
                    f"(pratica_id, nome_fornitore, importo, file_pdf, drive_file_id) "
                    f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
                    (pratica_id, nome_f, float(imp_f), pdf_path or None, drive_id or None),
                )

        return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id))

    # GET — crea subito una bozza vuota e apre le due schede (paziente da scegliere
    # nella scheda Codifica). Se si arriva da una scheda cliente, lo precolleghiamo
    # e copiamo ASL e medico curante dall'anagrafica.
    cliente_id = request.args.get("cliente_id") or None
    nome_paziente, asl, medico = "", "", ""
    with get_db() as conn:
        cur = conn.cursor()
        _, prov_default = provvigione_corrente(conn)
        if cliente_id:
            cur.execute(f"SELECT cognome, nome, asl, medico_curante FROM clienti WHERE id = {_PH}", (cliente_id,))
            c = cur.fetchone()
            if c:
                nome_paziente = (c["cognome"] + (f" {c['nome']}" if c["nome"] else "")).strip()
                asl = c["asl"] or ""
                medico = c["medico_curante"] or ""
            else:
                cliente_id = None
        cur.execute(
            f"INSERT INTO pratiche (nome_paziente, cliente_id, data_pratica, importo_asl, "
            f"importo_privato, provvigione_pct, asl_destinataria, medico_struttura) "
            f"VALUES ({_PH}, {_PH}, {_PH}, 0, 0, {_PH}, {_PH}, {_PH})",
            (nome_paziente, cliente_id, datetime.now().strftime("%Y-%m-%d"), prov_default, asl, medico),
        )
        pratica_id = last_inserted_id(cur)
    return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id))


# ── Dettaglio pratica ─────────────────────────────────────────────────────────

@app.route("/pratica/<int:pratica_id>")
def dettaglio_pratica(pratica_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM pratiche WHERE id = {_PH}", (pratica_id,))
        pratica = cur.fetchone()
        if not pratica:
            return "Pratica non trovata", 404
        cur.execute(f"SELECT * FROM preventivi WHERE pratica_id = {_PH}", (pratica_id,))
        preventivi = cur.fetchall()

        cliente = None
        if pratica["cliente_id"]:
            cur.execute(f"SELECT * FROM clienti WHERE id = {_PH}", (pratica["cliente_id"],))
            cliente = cur.fetchone()

        cur.execute(
            f"SELECT * FROM righe_ausili WHERE pratica_id = {_PH} ORDER BY ordine, id",
            (pratica_id,),
        )
        righe = cur.fetchall()

    costo_totale = sum(p["importo"] for p in preventivi)
    margine = calcola_margine(
        pratica["importo_asl"], costo_totale, pratica["provvigione_pct"],
        pratica["importo_privato"] or 0
    )
    # Totale imponibile righe ausili (per la sezione ausili / preventivo)
    tot_ausili = sum((r["qta"] or 0) * (r["prezzo_unitario"] or 0) for r in righe)
    # Moduli PDF: ordinati per categoria (preventivi → deleghe → resto)
    moduli = moduli_ordinati()
    # Moduli selezionati manualmente per questa pratica (id separati da virgola).
    # I preventivi sono sempre attivi (non disattivabili).
    moduli_attivi = {
        m for m in (pratica["moduli_attivi"] or "").split(",") if m
    } | set(MODULI_SEMPRE_ATTIVI)
    return render_template(
        "dettaglio_pratica.html",
        pratica=pratica,
        cliente=cliente,
        preventivi=preventivi,
        righe=righe,
        tot_ausili=tot_ausili,
        margine=margine,
        moduli=moduli,
        moduli_attivi=moduli_attivi,
        preset_categorie=preset_per_categoria(),
        significato_categorie=significato_per_categoria(),
        sign_catalogo=significato_catalogo(),
        sign_articoli=SIGNIFICATO_ARTICOLI,
        soglia_ok=MARGINE_SOGLIA_OK,
        soglia_warn=MARGINE_SOGLIA_WARN,
        asl_opzioni=opzioni_asl(),
    )


# ── Modifica pratica ──────────────────────────────────────────────────────────

@app.route("/pratica/<int:pratica_id>/modifica", methods=["GET", "POST"])
def modifica_pratica(pratica_id):
    if request.method == "POST":
        nome_paziente   = request.form["nome_paziente"].strip()
        data_pratica    = request.form["data_pratica"]
        importo_asl     = float(request.form["importo_asl"])
        importo_privato = float(request.form.get("importo_privato") or 0)
        provvigione_pct = float(request.form.get("provvigione_pct", PROVVIGIONE_PCT))
        note            = request.form.get("note", "").strip()

        fornitori = request.form.getlist("fornitore_nome[]")
        importi   = request.form.getlist("fornitore_importo[]")
        file_pdfs = request.form.getlist("fornitore_pdf[]")
        drive_ids = request.form.getlist("fornitore_drive_id[]")

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE pratiche SET nome_paziente={_PH}, data_pratica={_PH}, "
                f"importo_asl={_PH}, importo_privato={_PH}, provvigione_pct={_PH}, note={_PH} WHERE id={_PH}",
                (nome_paziente, data_pratica, importo_asl, importo_privato, provvigione_pct, note, pratica_id),
            )
            cur.execute(f"DELETE FROM preventivi WHERE pratica_id={_PH}", (pratica_id,))
            for i, (nome_f, imp_f) in enumerate(zip(fornitori, importi)):
                nome_f = nome_f.strip()
                if not nome_f or not imp_f:
                    continue
                pdf_path = file_pdfs[i] if i < len(file_pdfs) else None
                drive_id = drive_ids[i] if i < len(drive_ids) else None
                cur.execute(
                    f"INSERT INTO preventivi "
                    f"(pratica_id, nome_fornitore, importo, file_pdf, drive_file_id) "
                    f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
                    (pratica_id, nome_f, float(imp_f), pdf_path or None, drive_id or None),
                )

        return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id))

    # GET — carica dati esistenti
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM pratiche WHERE id = {_PH}", (pratica_id,))
        pratica = cur.fetchone()
        if not pratica:
            return "Pratica non trovata", 404
        cur.execute(f"SELECT * FROM preventivi WHERE pratica_id = {_PH}", (pratica_id,))
        preventivi = cur.fetchall()

    preventivi_json = json.dumps([{
        "nome_fornitore": p["nome_fornitore"],
        "importo":        p["importo"],
        "file_pdf":       p["file_pdf"] or "",
        "drive_file_id":  p["drive_file_id"] or "",
    } for p in preventivi])

    return render_template(
        "modifica_pratica.html",
        pratica=pratica,
        preventivi=preventivi,
        preventivi_json=preventivi_json,
        provvigione_std=PROVVIGIONE_PCT,
        provvigione_rid=PROVVIGIONE_PCT_RIDOTTA,
    )


# ── Segna/deseleziona fatturata ───────────────────────────────────────────────

@app.route("/pratica/<int:pratica_id>/fattura", methods=["POST"])
def fattura_pratica(pratica_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT fatturata FROM pratiche WHERE id = {_PH}", (pratica_id,))
        row = cur.fetchone()
        if not row:
            return "Pratica non trovata", 404

        attuale = bool(row["fatturata"])
        if attuale:
            cur.execute(
                f"UPDATE pratiche SET fatturata = {_PH}, data_fatturazione = NULL WHERE id = {_PH}",
                (False, pratica_id),
            )
        else:
            oggi = date.today().isoformat()
            cur.execute(
                f"UPDATE pratiche SET fatturata = {_PH}, data_fatturazione = {_PH} WHERE id = {_PH}",
                (True, oggi, pratica_id),
            )

    torna = request.form.get("torna", url_for("dashboard"))
    return redirect(torna)


# ── Aggiorna data ordine ──────────────────────────────────────────────────────

@app.route("/pratica/<int:pratica_id>/data-ordine", methods=["POST"])
def aggiorna_data_ordine(pratica_id):
    nuova_data = request.form.get("data_pratica", "").strip()
    if not nuova_data:
        torna = request.form.get("torna", url_for("dashboard"))
        return redirect(torna)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE pratiche SET data_pratica = {_PH} WHERE id = {_PH}",
            (nuova_data, pratica_id),
        )
    torna = request.form.get("torna", url_for("dashboard"))
    return redirect(torna)


# ── Aggiorna data fatturazione ────────────────────────────────────────────────

@app.route("/pratica/<int:pratica_id>/data-fattura", methods=["POST"])
def aggiorna_data_fattura(pratica_id):
    nuova_data = request.form.get("data_fatturazione", "").strip()
    if not nuova_data:
        torna = request.form.get("torna", url_for("dashboard"))
        return redirect(torna)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE pratiche SET data_fatturazione = {_PH} WHERE id = {_PH}",
            (nuova_data, pratica_id),
        )
    torna = request.form.get("torna", url_for("dashboard"))
    return redirect(torna)


# ── Aggiorna importo privato ──────────────────────────────────────────────────

@app.route("/pratica/<int:pratica_id>/importo-privato", methods=["POST"])
def aggiorna_importo_privato(pratica_id):
    try:
        importo = float(request.form.get("importo_privato") or 0)
    except ValueError:
        importo = 0.0
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE pratiche SET importo_privato = {_PH} WHERE id = {_PH}",
            (importo, pratica_id),
        )
    torna = request.form.get("torna", url_for("dashboard"))
    return redirect(torna)


# ── Lista fatturati ───────────────────────────────────────────────────────────

@app.route("/fatturati")
def fatturati():
    sql = f"""
        SELECT p.*,
               COALESCE(SUM(pr.importo), 0) AS costo_totale
        FROM pratiche p
        LEFT JOIN preventivi pr ON pr.pratica_id = p.id
        WHERE p.fatturata = {_FATTURATA_TRUE}
        GROUP BY p.id
        ORDER BY p.data_fatturazione DESC, p.data_pratica DESC
    """
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        pratiche_raw = cur.fetchall()

    righe = []
    for pr in pratiche_raw:
        m_dati = calcola_margine(pr["importo_asl"], pr["costo_totale"], pr["provvigione_pct"], pr["importo_privato"] or 0)
        righe.append({**dict(pr), **m_dati})

    # Raggruppa per mese di fatturazione
    mesi: dict = {}
    for p in righe:
        mese_k = str(p.get("data_fatturazione") or p["data_pratica"])[:7]
        mesi.setdefault(mese_k, {"pratiche": [], "totale_ricavi": 0.0, "totale_provvigioni": 0.0, "mol_totale": 0.0})
        mesi[mese_k]["pratiche"].append(p)
        mesi[mese_k]["totale_ricavi"]      += p["ricavi"]
        mesi[mese_k]["totale_provvigioni"] += p["provvigione"]
        mesi[mese_k]["mol_totale"]         += p["mol"]

    gruppi = [{"mese": k, **v} for k, v in sorted(mesi.items(), reverse=True)]

    return render_template(
        "fatturati.html",
        gruppi=gruppi,
        soglia_ok=MARGINE_SOGLIA_OK,
        soglia_warn=MARGINE_SOGLIA_WARN,
    )


# ── Aggiungi / rimuovi fornitore singolo ─────────────────────────────────────

@app.route("/pratica/<int:pratica_id>/fornitore/aggiungi", methods=["POST"])
def aggiungi_fornitore(pratica_id):
    nome_f  = request.form.get("nome_fornitore", "").strip()
    importo = request.form.get("importo", "").strip()
    torna   = request.form.get("torna", url_for("dettaglio_pratica", pratica_id=pratica_id))
    if nome_f and importo:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO preventivi (pratica_id, nome_fornitore, importo) VALUES ({_PH},{_PH},{_PH})",
                (pratica_id, nome_f, float(importo)),
            )
    return redirect(torna)


@app.route("/preventivo/<int:preventivo_id>/elimina", methods=["POST"])
def elimina_fornitore(preventivo_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT pratica_id FROM preventivi WHERE id={_PH}", (preventivo_id,))
        row = cur.fetchone()
        pratica_id = row["pratica_id"] if row else None
        cur.execute(f"DELETE FROM preventivi WHERE id={_PH}", (preventivo_id,))
    torna = request.form.get("torna")
    if torna:
        return redirect(torna)
    return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id) if pratica_id else url_for("dashboard"))


# ── Righe ausili (LEA) ────────────────────────────────────────────────────────

@app.route("/pratica/<int:pratica_id>/riga/aggiungi", methods=["POST"])
def aggiungi_riga(pratica_id):
    codice_iso  = (request.form.get("codice_iso") or "").strip()
    descrizione = (request.form.get("descrizione") or "").strip()
    try:
        qta = float(request.form.get("qta") or 1)
    except ValueError:
        qta = 1
    try:
        prezzo = float(request.form.get("prezzo_unitario") or 0)
    except ValueError:
        prezzo = 0
    if codice_iso or descrizione:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COALESCE(MAX(ordine), 0) + 1 AS o FROM righe_ausili WHERE pratica_id = {_PH}",
                (pratica_id,),
            )
            ordine = cur.fetchone()["o"]
            cur.execute(
                f"INSERT INTO righe_ausili (pratica_id, codice_iso, descrizione, qta, prezzo_unitario, ordine) "
                f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
                (pratica_id, codice_iso, descrizione, qta, prezzo, ordine),
            )
    return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id) + "#ausili")


@app.route("/pratica/<int:pratica_id>/preset", methods=["POST"])
def applica_preset(pratica_id):
    """Inserisce in blocco tutte le righe del preset selezionato."""
    preset = get_preset(request.form.get("preset_id", ""))
    if preset:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT COALESCE(MAX(ordine), 0) AS o FROM righe_ausili WHERE pratica_id = {_PH}",
                (pratica_id,),
            )
            ordine = cur.fetchone()["o"]
            for r in preset.get("righe", []):
                ordine += 1
                cur.execute(
                    f"INSERT INTO righe_ausili (pratica_id, codice_iso, descrizione, qta, prezzo_unitario, ordine) "
                    f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
                    (pratica_id, r.get("codice_iso", ""), r.get("descrizione", ""),
                     r.get("qta", 1), r.get("prezzo_unitario", 0), ordine),
                )
    return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id) + "#ausili")


@app.route("/pratica/<int:pratica_id>/righe/svuota", methods=["POST"])
def svuota_righe(pratica_id):
    """Cancella tutte le righe ausili della pratica."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM righe_ausili WHERE pratica_id = {_PH}", (pratica_id,))
    return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id) + "#ausili")


@app.route("/riga/<int:riga_id>/qta", methods=["POST"])
def aggiorna_qta_riga(riga_id):
    """Aggiorna la quantità di una riga ausilio e restituisce i totali ricalcolati."""
    try:
        qta = float(request.form.get("qta") or 0)
    except ValueError:
        qta = 0
    if qta < 0:
        qta = 0
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT pratica_id, prezzo_unitario FROM righe_ausili WHERE id = {_PH}", (riga_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"ok": False}), 404
        pratica_id = row["pratica_id"]
        prezzo = row["prezzo_unitario"] or 0
        cur.execute(f"UPDATE righe_ausili SET qta = {_PH} WHERE id = {_PH}", (qta, riga_id))
        cur.execute(
            f"SELECT COALESCE(SUM(qta * prezzo_unitario), 0) AS tot, COUNT(*) AS n "
            f"FROM righe_ausili WHERE pratica_id = {_PH}",
            (pratica_id,),
        )
        r = cur.fetchone()
        tot_ausili = float(r["tot"] or 0)
        n_righe = int(r["n"] or 0)
    return jsonify({"ok": True, "qta": qta, "riga_tot": qta * float(prezzo),
                    "tot_ausili": tot_ausili, "n_righe": n_righe})


@app.route("/pratica/<int:pratica_id>/righe/elimina", methods=["POST"])
def elimina_righe_multiple(pratica_id):
    """Elimina in blocco le righe ausili selezionate (lista di id)."""
    ids = [int(x) for x in request.form.getlist("riga_id[]") if x.isdigit()]
    tot_ausili = 0.0
    n_righe = 0
    with get_db() as conn:
        cur = conn.cursor()
        if ids:
            ph = ", ".join([_PH] * len(ids))
            cur.execute(
                f"DELETE FROM righe_ausili WHERE pratica_id = {_PH} AND id IN ({ph})",
                (pratica_id, *ids),
            )
        cur.execute(
            f"SELECT COALESCE(SUM(qta * prezzo_unitario), 0) AS tot, COUNT(*) AS n "
            f"FROM righe_ausili WHERE pratica_id = {_PH}",
            (pratica_id,),
        )
        r = cur.fetchone()
        tot_ausili = float(r["tot"] or 0)
        n_righe = int(r["n"] or 0)
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True, "eliminati": ids, "tot_ausili": tot_ausili, "n_righe": n_righe})
    return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id) + "#ausili")


@app.route("/riga/<int:riga_id>/elimina", methods=["POST"])
def elimina_riga(riga_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT pratica_id FROM righe_ausili WHERE id = {_PH}", (riga_id,))
        row = cur.fetchone()
        pratica_id = row["pratica_id"] if row else None
        cur.execute(f"DELETE FROM righe_ausili WHERE id = {_PH}", (riga_id,))
        tot_ausili = 0.0
        n_righe = 0
        if pratica_id:
            cur.execute(
                f"SELECT COALESCE(SUM(qta * prezzo_unitario), 0) AS tot, COUNT(*) AS n "
                f"FROM righe_ausili WHERE pratica_id = {_PH}",
                (pratica_id,),
            )
            r = cur.fetchone()
            tot_ausili = float(r["tot"] or 0)
            n_righe = int(r["n"] or 0)

    # Richiesta AJAX (fetch): niente reload, rispondiamo coi totali aggiornati
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True, "tot_ausili": tot_ausili, "n_righe": n_righe})

    if pratica_id:
        return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id) + "#ausili")
    return redirect(url_for("dashboard"))


@app.route("/pratica/<int:pratica_id>/importo-asl", methods=["POST"])
def aggiorna_importo_asl(pratica_id):
    """Aggiorna l'importo ASL (precompilato dai codici, ma modificabile)."""
    try:
        importo = float(request.form.get("importo_asl") or 0)
    except ValueError:
        importo = 0.0
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE pratiche SET importo_asl = {_PH} WHERE id = {_PH}",
            (importo, pratica_id),
        )
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True, "importo_asl": importo})
    torna = request.form.get("torna", url_for("dettaglio_pratica", pratica_id=pratica_id) + "#tab-margine")
    return redirect(torna)


@app.route("/pratica/<int:pratica_id>/moduli-attivi", methods=["POST"])
def aggiorna_moduli_attivi(pratica_id):
    """Salva quali moduli PDF sono attivi per la pratica (selezione manuale)."""
    scelti = {m for m in request.form.getlist("modulo[]") if m in PDF_TEMPLATES}
    scelti |= set(MODULI_SEMPRE_ATTIVI)  # i preventivi restano sempre attivi
    valore = ",".join(scelti)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE pratiche SET moduli_attivi = {_PH} WHERE id = {_PH}",
            (valore, pratica_id),
        )
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True, "moduli_attivi": scelti})
    return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id) + "#moduli")


# ── Elimina pratica ───────────────────────────────────────────────────────────

@app.route("/pratica/<int:pratica_id>/elimina", methods=["POST"])
def elimina_pratica(pratica_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM righe_ausili WHERE pratica_id = {_PH}", (pratica_id,))
        cur.execute(f"DELETE FROM preventivi WHERE pratica_id = {_PH}", (pratica_id,))
        cur.execute(f"DELETE FROM pratiche WHERE id = {_PH}", (pratica_id,))
    torna = request.form.get("torna")
    return redirect(torna or url_for("dashboard"))


# ── Catalogo significato terapeutico (globale, editabile via AJAX) ────────────

@app.route("/significato/aggiungi", methods=["POST"])
def significato_aggiungi():
    articolo = (request.form.get("articolo") or "").strip()
    testo    = (request.form.get("testo") or "").strip()
    if articolo not in SIGNIFICATO_ARTICOLI or not testo:
        return jsonify({"ok": False, "errore": "Articolo o testo non validi"}), 400
    mot_id = aggiungi_motivazione(articolo, testo)
    return jsonify({"ok": True, "id": mot_id, "articolo": articolo, "testo": testo})


@app.route("/significato/<int:mot_id>/modifica", methods=["POST"])
def significato_modifica(mot_id):
    testo = (request.form.get("testo") or "").strip()
    if not testo:
        return jsonify({"ok": False, "errore": "Testo vuoto"}), 400
    aggiorna_motivazione(mot_id, testo)
    return jsonify({"ok": True, "id": mot_id, "testo": testo})


@app.route("/significato/<int:mot_id>/elimina", methods=["POST"])
def significato_elimina(mot_id):
    elimina_motivazione(mot_id)
    return jsonify({"ok": True, "id": mot_id})


# ── API: estrai totale da PDF ─────────────────────────────────────────────────

@app.route("/api/estrai-pdf", methods=["POST"])
def api_estrai_pdf():
    if "pdf" not in request.files:
        return jsonify({"errore": "Nessun file"}), 400
    file = request.files["pdf"]
    if not file or not _allowed_file(file.filename):
        return jsonify({"errore": "File non valido (solo PDF)"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    risultato = estrai_totale_pdf(filepath)
    if not risultato.get("errore") and os.path.exists(filepath):
        risultato["filepath"] = os.path.join(UPLOAD_FOLDER, filename)

    return jsonify(risultato)


# ── API: sincronizza Drive ────────────────────────────────────────────────────

@app.route("/api/sync-drive")
def api_sync_drive():
    if not drive_configurato():
        return jsonify({"errore": "Google Drive non configurato"}), 503

    from drive_sync import lista_pdf_drive, scarica_pdf_temp

    # ID già importati: non vanno riproposti
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT drive_file_id FROM preventivi WHERE drive_file_id IS NOT NULL"
        )
        importati = {r["drive_file_id"] for r in cur.fetchall()}

    try:
        nuovi = lista_pdf_drive(importati)
    except Exception as e:
        return jsonify({"errore": str(e)}), 500

    risultati = []
    for f in nuovi[:20]:  # max 20 per chiamata
        tmp_path = None
        try:
            tmp_path = scarica_pdf_temp(f["id"])
            estratto = estrai_totale_pdf(tmp_path)
            risultati.append({
                "drive_file_id": f["id"],
                "nome_file":     f["name"],
                "suggerito":     estratto.get("suggerito"),
                "candidati":     estratto.get("candidati", []),
                "errore":        estratto.get("errore"),
            })
        except Exception as e:
            risultati.append({
                "drive_file_id": f["id"],
                "nome_file":     f["name"],
                "suggerito":     None,
                "candidati":     [],
                "errore":        str(e),
            })
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    return jsonify({"nuovi": risultati, "totale_drive": len(nuovi)})


# ── API: calcola margine ──────────────────────────────────────────────────────

@app.route("/api/calcola-margine")
def api_calcola_margine():
    try:
        asl          = float(request.args.get("asl", 0))
        costo        = float(request.args.get("costo", 0))
        prov_pct     = float(request.args.get("provvigione_pct", PROVVIGIONE_PCT))
        privato      = float(request.args.get("privato", 0))
    except (ValueError, TypeError):
        return jsonify({"errore": "Valori non validi"}), 400
    return jsonify(calcola_margine(asl, costo, prov_pct, privato))


# ── API: costanti di configurazione ──────────────────────────────────────────

@app.route("/api/config")
def api_config():
    return jsonify({
        "provvigione_pct":         PROVVIGIONE_PCT * 100,
        "provvigione_pct_ridotta": PROVVIGIONE_PCT_RIDOTTA * 100,
        "struttura_pct":           STRUTTURA_PCT * 100,
        "margine_soglia_ok":       MARGINE_SOGLIA_OK,
        "margine_soglia_warn":     MARGINE_SOGLIA_WARN,
    })


# ── Dati per i moduli (campi clinici della pratica) ───────────────────────────

# Campi testo dei moduli (iva_percentuale gestita a parte perché numerica)
_PRATICA_MODULO_FIELDS = [
    "numero_pratica", "ausilio", "asl_destinataria", "medico_struttura",
    "diagnosi", "sign_terapeutico",
]


@app.route("/pratica/<int:pratica_id>/dati-moduli", methods=["POST"])
def aggiorna_dati_moduli(pratica_id):
    valori = [(request.form.get(c) or "").strip() for c in _PRATICA_MODULO_FIELDS]
    set_clause = ", ".join(f"{c} = {_PH}" for c in _PRATICA_MODULO_FIELDS)
    params = list(valori)
    # Paziente / collegamento anagrafica (scelti nella scheda Codifica): aggiornati
    # solo se il form li invia, così non sovrascriviamo per errore.
    if "nome_paziente" in request.form:
        set_clause += f", nome_paziente = {_PH}"
        params.append((request.form.get("nome_paziente") or "").strip())
        set_clause += f", cliente_id = {_PH}"
        params.append(request.form.get("cliente_id") or None)
    # L'IVA non è più nell'interfaccia: la aggiorniamo solo se il form la invia,
    # altrimenti resta il valore esistente (default 4).
    iva_raw = request.form.get("iva_percentuale")
    if iva_raw is not None:
        try:
            iva = float(iva_raw or 4)
        except ValueError:
            iva = 4
        set_clause += f", iva_percentuale = {_PH}"
        params.append(iva)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE pratiche SET {set_clause} WHERE id = {_PH}",
            tuple(params) + (pratica_id,),
        )
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({
            "ok": True,
            "nome_paziente": (request.form.get("nome_paziente") or "").strip(),
            "cliente_id": (request.form.get("cliente_id") or "").strip(),
        })
    return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id) + "#moduli")


# ── Generazione modulo PDF ────────────────────────────────────────────────────

@app.route("/pratica/<int:pratica_id>/modulo/<template_id>")
def genera_modulo(pratica_id, template_id):
    if template_id not in PDF_TEMPLATES:
        return "Modulo non disponibile", 404

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM pratiche WHERE id = {_PH}", (pratica_id,))
        pratica = cur.fetchone()
        if not pratica:
            return "Pratica non trovata", 404
        cliente = None
        if pratica["cliente_id"]:
            cur.execute(f"SELECT * FROM clienti WHERE id = {_PH}", (pratica["cliente_id"],))
            cliente = cur.fetchone()
        cur.execute(
            f"SELECT * FROM righe_ausili WHERE pratica_id = {_PH} ORDER BY ordine, id",
            (pratica_id,),
        )
        righe = [dict(r) for r in cur.fetchall()]

    pratica_d = dict(pratica)
    cliente_d = dict(cliente) if cliente else None

    if PDF_TEMPLATES[template_id].get("richiede_cliente") and not cliente_d:
        # Senza cliente collegato non c'è anagrafica da inserire nel modulo
        return redirect(url_for("dettaglio_pratica", pratica_id=pratica_id) + "#moduli")

    # Per le DELEGHE chiediamo conferma della data di prescrizione: senza il
    # parametro mostriamo una paginetta che la propone (default = data pratica)
    # e permette di correggerla prima di generare.
    if PDF_TEMPLATES[template_id].get("categoria") == "delega":
        data_conf = (request.args.get("data_prescrizione") or "").strip()
        if not data_conf:
            return render_template(
                "conferma_data_delega.html",
                pratica=pratica_d, cliente=cliente_d, template_id=template_id,
                template_label=PDF_TEMPLATES[template_id].get("label", template_id),
                data_default=str(pratica_d.get("data_pratica") or "")[:10],
            )
        pratica_d["data_pratica"] = data_conf

    # N° pratica generato in automatico alla prima generazione di un preventivo,
    # poi salvato sulla pratica così resta stabile (per le pratiche già create lo
    # si inserisce a mano dalla scheda Codifica).
    if (PDF_TEMPLATES[template_id].get("categoria") == "preventivo"
            and not (pratica_d.get("numero_pratica") or "").strip()):
        num = numero_preventivo(pratica_d, cliente_d)
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE pratiche SET numero_pratica = {_PH} WHERE id = {_PH}",
                (num, pratica_id),
            )
        pratica_d["numero_pratica"] = num

    try:
        pdf_bytes = compila_pdf(template_id, pratica_d, cliente_d, righe)
    except Exception as e:
        import sys, traceback
        print("ERRORE GENERAZIONE PDF:", e, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return f"Errore nella generazione del modulo: {e}", 500

    filename = nome_file_consigliato(template_id, pratica_d, cliente_d)
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Gestione preset ausili ────────────────────────────────────────────────────

def _leggi_righe_preset(form) -> list:
    """Estrae le righe dal form del preset (array paralleli)."""
    cods   = form.getlist("codice_iso[]")
    descs  = form.getlist("descrizione[]")
    qtas   = form.getlist("qta[]")
    prezzi = form.getlist("prezzo_unitario[]")
    n = max(len(cods), len(descs), len(qtas), len(prezzi))
    righe = []
    for i in range(n):
        def g(lst):
            return lst[i] if i < len(lst) else ""
        try:
            qta = float(g(qtas)) if g(qtas) else 1
        except ValueError:
            qta = 1
        try:
            prezzo = float(g(prezzi)) if g(prezzi) else 0
        except ValueError:
            prezzo = 0
        righe.append({
            "codice_iso": g(cods).strip(),
            "descrizione": g(descs).strip(),
            "qta": qta,
            "prezzo_unitario": prezzo,
        })
    return righe


@app.route("/presets")
def presets():
    return render_template("presets.html", categorie=preset_per_categoria())


@app.route("/preset/nuovo", methods=["GET", "POST"])
def preset_nuovo():
    if request.method == "POST":
        label = (request.form.get("label") or "").strip()
        categoria = (request.form.get("categoria") or "").strip()
        righe = _leggi_righe_preset(request.form)
        if not label:
            return render_template("preset_form.html", preset={"righe": righe, "categoria": categoria},
                                   categorie_note=categorie_note(), errore="Il nome del set è obbligatorio.", modifica=False)
        pid = crea_preset(label, categoria, righe)
        return redirect(url_for("presets") + f"#preset-{pid}")
    return render_template("preset_form.html", preset={"righe": []},
                           categorie_note=categorie_note(), errore=None, modifica=False)


@app.route("/preset/<int:preset_id>/modifica", methods=["GET", "POST"])
def preset_modifica(preset_id):
    if request.method == "POST":
        label = (request.form.get("label") or "").strip()
        categoria = (request.form.get("categoria") or "").strip()
        righe = _leggi_righe_preset(request.form)
        if not label:
            preset = {"id": preset_id, "label": label, "categoria": categoria, "righe": righe}
            return render_template("preset_form.html", preset=preset,
                                   categorie_note=categorie_note(), errore="Il nome del set è obbligatorio.", modifica=True)
        aggiorna_preset(preset_id, label, categoria, righe)
        return redirect(url_for("presets") + f"#preset-{preset_id}")

    preset = get_preset(preset_id)
    if not preset:
        return "Preset non trovato", 404
    return render_template("preset_form.html", preset=preset,
                           categorie_note=categorie_note(), errore=None, modifica=True)


@app.route("/preset/<int:preset_id>/elimina", methods=["POST"])
def preset_elimina(preset_id):
    elimina_preset(preset_id)
    return redirect(url_for("presets"))


# ── Anagrafica clienti ────────────────────────────────────────────────────────

# Campi del modello cliente scrivibili da form (esclusi id e creato_il).
CLIENTE_FIELDS = [
    "cognome", "nome", "codice_fiscale", "data_nascita", "luogo_nascita",
    "provincia", "residenza_via", "residenza_civico", "residenza_citta",
    "residenza_cap", "residente_dal_anno", "telefono", "email", "asl", "centro",
    "medico_curante",
    "decorrenza_residenza", "documento_tipo_numero", "documento_rilascio_luogo",
    "documento_data_rilascio",
    # Tutore legale (delegato delle deleghe): flag + dati documento
    "ha_tutore", "tutore_nome", "tutore_cf", "tutore_documento_tipo_numero",
    "tutore_documento_rilascio_luogo", "tutore_documento_rilascio_data",
    "note",
]
# Campi data: stringa vuota → NULL (SQLite/Postgres non accettano '' su DATE)
_CLIENTE_DATE_FIELDS = {
    "data_nascita", "decorrenza_residenza", "documento_data_rilascio",
    "tutore_documento_rilascio_data",
}
# Campi checkbox → Python bool. IMPORTANTE: bool (non int 0/1) perché su
# PostgreSQL la colonna è BOOLEAN e un int provoca errore di tipo all'INSERT.
# Su SQLite il bool è comunque memorizzato come 0/1.
_CLIENTE_BOOL_FIELDS = {"ha_tutore"}
# Normalizzazione maiuscole: CF/provincia/CF tutore = tutto maiuscolo;
# gli altri testi = solo l'iniziale. Questi restano invariati.
_CLIENTE_UPPER_FIELDS = {"codice_fiscale", "provincia", "tutore_cf"}
_CLIENTE_NO_CAP_FIELDS = {"email", "asl", "centro", "telefono", "residenza_cap",
                          "residente_dal_anno"}


def _leggi_cliente_dal_form(form) -> dict:
    """Estrae i campi cliente dal form, normalizzando vuoti, date, checkbox e
    maiuscole (CF in maiuscolo, gli altri testi con l'iniziale maiuscola)."""
    dati = {}
    for campo in CLIENTE_FIELDS:
        if campo in _CLIENTE_BOOL_FIELDS:
            dati[campo] = bool(form.get(campo))
            continue
        val = (form.get(campo) or "").strip()
        if campo in _CLIENTE_DATE_FIELDS and not val:
            val = None
        elif val and campo in _CLIENTE_UPPER_FIELDS:
            val = val.upper()
        elif val and campo not in _CLIENTE_NO_CAP_FIELDS and campo not in _CLIENTE_DATE_FIELDS:
            val = val[:1].upper() + val[1:]
        dati[campo] = val
    return dati


# ── Opzioni tendine Centro / ASL ─────────────────────────────────────────────
# Le tendine mostrano i valori "seme" (config) UNITI a quelli già salvati nel DB,
# così un nuovo centro/ASL aggiunto e salvato resta disponibile nelle selezioni
# successive. I nomi colonna sono costanti interne (non input utente).
def _opzioni(seed, query, params=()) -> list:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        usati = [(r["v"] or "").strip() for r in cur.fetchall()]
    seen = {s.lower() for s in seed}
    extra = []
    for u in usati:
        if u and u.lower() not in seen:
            seen.add(u.lower())
            extra.append(u)
    return list(seed) + sorted(extra, key=str.lower)


def opzioni_centri() -> list:
    return _opzioni(CENTRI, "SELECT DISTINCT centro AS v FROM clienti WHERE COALESCE(centro,'') <> ''")


def opzioni_asl() -> list:
    # unione di clienti.asl e pratiche.asl_destinataria (entrambi rappresentano la ASL)
    return _opzioni(
        ASL_OPZIONI,
        "SELECT asl AS v FROM clienti WHERE COALESCE(asl,'') <> '' "
        "UNION SELECT asl_destinataria AS v FROM pratiche WHERE COALESCE(asl_destinataria,'') <> ''",
    )


# Ordina i centri: prima quelli in CENTRI (nell'ordine della costante), poi gli
# altri valori a mano in ordine alfabetico, infine "Senza centro" in coda.
def _raggruppa_per_centro(righe) -> list:
    """Raggruppa una lista di righe (dict-like con chiave 'centro') in
    [(nome_centro, [righe…]), …] ordinato secondo CENTRI, preservando l'ordine
    interno già stabilito dalla query (es. data di apertura)."""
    gruppi: dict[str, list] = {}
    for r in righe:
        nome = (r["centro"] or "").strip() or "Senza centro"
        gruppi.setdefault(nome, []).append(r)

    def chiave(nome: str):
        if nome == "Senza centro":
            return (2, "")
        if nome in CENTRI:
            return (0, CENTRI.index(nome))
        return (1, nome.lower())

    return [(nome, gruppi[nome]) for nome in sorted(gruppi, key=chiave)]


# ── Colonne configurabili delle liste ────────────────────────────────────────
# Catalogo delle colonne opzionali. "Cliente"/"Paziente" e le azioni sono fisse.
# Default = colonne mostrate finché l'utente non personalizza (via cookie cols_*).

COLONNE_CLIENTI = [
    {"key": "cf",           "label": "Codice Fiscale", "default": True},
    {"key": "telefono",     "label": "Telefono",       "default": True},
    {"key": "email",        "label": "Email",          "default": False},
    {"key": "asl",          "label": "ASL",            "default": True},
    {"key": "medico",       "label": "Medico curante", "default": False},
    {"key": "nascita",      "label": "Data nascita",   "default": False},
    {"key": "luogo",        "label": "Luogo nascita",  "default": False},
    {"key": "residenza",    "label": "Residenza",      "default": False},
    {"key": "apertura",     "label": "Apertura",       "default": True},
    {"key": "num_pratiche", "label": "N° pratiche",    "default": True},
]

COLONNE_PRATICHE = [
    {"key": "data",    "label": "Data",            "default": True},
    {"key": "numero",  "label": "N° pratica",      "default": True},
    {"key": "asl",     "label": "Importo ASL",     "default": True},
    {"key": "privato", "label": "Importo privato", "default": False},
    {"key": "costo",   "label": "Costo fornitori", "default": True},
    {"key": "mol",     "label": "MOL",             "default": False},
    {"key": "margine", "label": "Margine %",       "default": False},
    {"key": "stato",   "label": "Stato",           "default": True},
]


def _colonne_attive(nome: str, catalogo: list) -> list:
    """Legge dal cookie cols_<nome> le colonne scelte, mantenendo l'ordine del
    catalogo. Senza cookie usa i default. Cookie vuoto/'none' = nessuna opzionale."""
    raw = request.cookies.get("cols_" + nome)
    if raw is None:
        return [c["key"] for c in catalogo if c["default"]]
    scelte = set(raw.split(","))
    return [c["key"] for c in catalogo if c["key"] in scelte]


@app.route("/clienti")
def clienti():
    q = (request.args.get("q") or "").strip()
    centro = (request.args.get("centro") or "").strip()
    solo_verificare = request.args.get("da_verificare") == "1"
    where, params = [], []
    if q:
        like = f"%{q}%"
        where.append(f"(c.cognome LIKE {_PH} OR c.nome LIKE {_PH} OR c.codice_fiscale LIKE {_PH})")
        params += [like, like, like]
    if centro:
        where.append(f"COALESCE(c.centro, '') = {_PH}")
        params.append("" if centro == "Senza centro" else centro)
    if solo_verificare:
        where.append("c.da_verificare")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    with get_db() as conn:
        cur = conn.cursor()
        # Ordine: per centro (i NULL/vuoti in fondo), poi data di apertura (creato_il) decrescente
        cur.execute(
            f"""SELECT c.*, COUNT(p.id) AS num_pratiche
                FROM clienti c
                LEFT JOIN pratiche p ON p.cliente_id = c.id
                {where_sql}
                GROUP BY c.id
                ORDER BY (c.centro IS NULL OR c.centro = ''), c.centro, c.creato_il DESC, c.cognome""",
            tuple(params),
        )
        elenco = cur.fetchall()
        cur.execute("SELECT COUNT(*) AS n FROM clienti WHERE da_verificare")
        n_verificare = cur.fetchone()["n"]
    gruppi = _raggruppa_per_centro(elenco)
    return render_template(
        "clienti.html", clienti=elenco, gruppi=gruppi, q=q,
        centro=centro, centri=opzioni_centri(),
        n_verificare=n_verificare, solo_verificare=solo_verificare,
        colonne_catalogo=COLONNE_CLIENTI,
        colonne_attive=_colonne_attive("clienti", COLONNE_CLIENTI),
    )


@app.route("/pratiche")
def pratiche():
    """Scheda di tutte le pratiche, raggruppate per Centro (del cliente) e
    ordinate per data, con la stessa ricerca dei clienti."""
    q = (request.args.get("q") or "").strip()
    centro = (request.args.get("centro") or "").strip()
    where, params = [], []
    if q:
        like = f"%{q}%"
        where.append(
            f"(p.nome_paziente LIKE {_PH} OR c.cognome LIKE {_PH} OR c.nome LIKE {_PH} "
            f"OR c.codice_fiscale LIKE {_PH} OR p.numero_pratica LIKE {_PH})"
        )
        params += [like, like, like, like, like]
    if centro:
        where.append(f"COALESCE(c.centro, '') = {_PH}")
        params.append("" if centro == "Senza centro" else centro)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT p.*, c.centro, c.cognome, c.nome, c.codice_fiscale,
                       COALESCE(SUM(pr.importo), 0) AS costo_totale
                FROM pratiche p
                LEFT JOIN clienti c    ON c.id = p.cliente_id
                LEFT JOIN preventivi pr ON pr.pratica_id = p.id
                {where_sql}
                GROUP BY p.id, c.id
                ORDER BY (c.centro IS NULL OR c.centro = ''), c.centro,
                         p.data_pratica DESC""",
            tuple(params),
        )
        elenco = [dict(r) for r in cur.fetchall()]
    # MOL e margine % per riga (per le colonne opzionali)
    for p in elenco:
        m = calcola_margine(
            p.get("importo_asl") or 0,
            p.get("costo_totale") or 0,
            p.get("provvigione_pct") or PROVVIGIONE_PCT,
            p.get("importo_privato") or 0,
        )
        p["mol"] = m["mol"]
        p["margine_pct"] = m["margine_pct"]
        if m["margine_pct"] >= MARGINE_SOGLIA_OK:
            p["margine_classe"] = "success"
        elif m["margine_pct"] >= MARGINE_SOGLIA_WARN:
            p["margine_classe"] = "warning"
        else:
            p["margine_classe"] = "danger"
    gruppi = _raggruppa_per_centro(elenco)
    return render_template(
        "pratiche.html", pratiche=elenco, gruppi=gruppi, q=q,
        centro=centro, centri=opzioni_centri(),
        colonne_catalogo=COLONNE_PRATICHE,
        colonne_attive=_colonne_attive("pratiche", COLONNE_PRATICHE),
    )


@app.route("/cliente/nuovo", methods=["GET", "POST"])
def cliente_nuovo():
    if request.method == "POST":
        dati = _leggi_cliente_dal_form(request.form)
        if not dati["cognome"]:
            return render_template("cliente_form.html", cliente=dati, errore="Il cognome è obbligatorio.", modifica=False, centri=opzioni_centri(), asl_opzioni=opzioni_asl())
        cols = ", ".join(CLIENTE_FIELDS)
        ph = ", ".join([_PH] * len(CLIENTE_FIELDS))
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO clienti ({cols}) VALUES ({ph})",
                tuple(dati[c] for c in CLIENTE_FIELDS),
            )
            cliente_id = last_inserted_id(cur)
        return redirect(url_for("cliente_dettaglio", cliente_id=cliente_id))
    # Precompila cognome/nome se arriva dal campo paziente di una pratica
    prefill = {
        "cognome": (request.args.get("cognome") or "").strip(),
        "nome":    (request.args.get("nome") or "").strip(),
    }
    return render_template("cliente_form.html", cliente=prefill, errore=None, modifica=False, centri=opzioni_centri(), asl_opzioni=opzioni_asl())


# Campi mostrati nel form mobile rapido (sottoinsieme essenziale di CLIENTE_FIELDS).
# Gli altri campi anagrafici (documento, email, note, decorrenza) restano vuoti
# e si completano poi dalla scheda cliente.
_MOBILE_FIELDS = [
    "cognome", "nome", "codice_fiscale", "data_nascita", "luogo_nascita",
    "residenza_via", "residenza_civico", "residenza_citta", "provincia",
    "residenza_cap", "telefono", "asl", "medico_curante", "centro",
]


@app.route("/mobile")
def mobile_qr():
    """Pagina desktop con il QR da inquadrare col tablet per aprire il form rapido."""
    mobile_url = url_for("mobile_nuovo", _external=True)
    paziente_url = url_for("modulo_paziente", _external=True)
    return render_template("mobile_qr.html", mobile_url=mobile_url, paziente_url=paziente_url)


@app.route("/mobile/nuovo", methods=["GET", "POST"])
def mobile_nuovo():
    """Form rapido ottimizzato per tablet: compila l'anagrafica essenziale,
    salva il cliente e apre subito la bozza pratica collegata."""
    if request.method == "POST":
        dati = _leggi_cliente_dal_form(request.form)  # legge tutti i CLIENTE_FIELDS
        if not dati["cognome"]:
            return render_template("mobile_nuovo.html", cliente=dati,
                                   errore="Il cognome è obbligatorio.",
                                   centri=opzioni_centri(), asl_opzioni=opzioni_asl(),
                                   ai_attivo=bool(ANTHROPIC_API_KEY))
        cols = ", ".join(CLIENTE_FIELDS)
        ph = ", ".join([_PH] * len(CLIENTE_FIELDS))
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"INSERT INTO clienti ({cols}) VALUES ({ph})",
                tuple(dati[c] for c in CLIENTE_FIELDS),
            )
            cliente_id = last_inserted_id(cur)
        # Crea la bozza pratica per questo cliente (copia ASL/medico) e la apre
        return redirect(url_for("nuova_pratica", cliente_id=cliente_id))
    return render_template("mobile_nuovo.html", cliente={}, errore=None,
                           centri=opzioni_centri(), asl_opzioni=opzioni_asl(),
                           ai_attivo=bool(ANTHROPIC_API_KEY))


# ── Note / Task collegati al cliente ─────────────────────────────────────────
# Note rapide salvate da mobile e ritrovate sulla scheda del cliente.
NOTE_TIPI      = ["Assistenza", "Valutazione", "Documenti"]
# Sottoscelta grafica disponibile quando il tipo è "Documenti"
NOTE_SOTTOTIPI = ["Relazione", "Documenti", "Ordine"]
NOTE_PRIORITA  = ["Media", "Alta", "Urgente"]
NOTE_STATI     = ["Aperta", "In lavorazione", "Completata"]


def _crea_nota(form) -> int:
    """Inserisce una nota dai campi del form. Restituisce l'id creato.
    `cliente_id` è opzionale: senza cliente la nota resta 'libera' col solo nominativo."""
    cliente_id = (form.get("cliente_id") or "").strip() or None
    nominativo = (form.get("nominativo") or "").strip()
    tipo       = (form.get("tipo") or "Assistenza").strip()
    # Il sottotipo ha senso solo per "Documenti": altrove lo azzeriamo.
    sottotipo  = (form.get("sottotipo") or "").strip() if tipo == "Documenti" else ""
    priorita   = (form.get("priorita") or "Media").strip()
    testo      = (form.get("testo") or "").strip()
    scadenza   = (form.get("scadenza") or "").strip() or None

    # Se è collegata a un cliente ma manca il nominativo, lo ricaviamo dall'anagrafica.
    if cliente_id and not nominativo:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT cognome, nome FROM clienti WHERE id = {_PH}", (cliente_id,))
            row = cur.fetchone()
            if row:
                nominativo = f"{row['cognome']} {row['nome']}".strip()

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""INSERT INTO note (cliente_id, nominativo, tipo, sottotipo, priorita, stato, completata, testo, scadenza)
                VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})""",
            (cliente_id, nominativo, tipo, sottotipo, priorita, "Aperta", False, testo, scadenza),
        )
        return last_inserted_id(cur)


@app.route("/note")
def note_inbox():
    """Elenco note: di default le aperte, con evidenza alle pratiche ferme (>7 giorni)."""
    filtro = request.args.get("filtro", "aperte")  # aperte | tutte | ferme
    where = ""
    if filtro == "aperte":
        where = "WHERE NOT n.completata"
    elif filtro == "ferme":
        where = ("WHERE NOT n.completata AND n.creato_il <= "
                 + ("NOW() - INTERVAL '7 days'" if _IS_POSTGRES_NOTE() else "datetime('now','-7 days')"))
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT n.*, c.cognome AS c_cognome, c.nome AS c_nome
                FROM note n
                LEFT JOIN clienti c ON c.id = n.cliente_id
                {where}
                ORDER BY n.completata ASC, COALESCE(n.scadenza, '9999-12-31') ASC, n.creato_il DESC"""
        )
        note = cur.fetchall()
    return render_template("note_inbox.html", note=note, filtro=filtro,
                           NOTE_PRIORITA=NOTE_PRIORITA)


@app.route("/note/nuova", methods=["GET", "POST"])
def note_nuova():
    """Form mobile-first per salvare una nota veloce, collegabile a un cliente."""
    if request.method == "POST":
        if not (request.form.get("testo") or "").strip():
            return render_template("note_nuova.html", errore="Scrivi il testo della nota.",
                                   nota=request.form, NOTE_TIPI=NOTE_TIPI,
                                   NOTE_SOTTOTIPI=NOTE_SOTTOTIPI, NOTE_PRIORITA=NOTE_PRIORITA)
        _crea_nota(request.form)
        # Torna alla scheda cliente se collegata, altrimenti all'inbox note.
        cid = (request.form.get("cliente_id") or "").strip()
        if cid:
            return redirect(url_for("cliente_dettaglio", cliente_id=cid))
        return redirect(url_for("note_inbox"))
    # Precompilazione opzionale quando si arriva da una scheda cliente.
    cliente = None
    cid = request.args.get("cliente_id")
    if cid:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT id, cognome, nome FROM clienti WHERE id = {_PH}", (cid,))
            cliente = cur.fetchone()
    return render_template("note_nuova.html", errore=None, nota={}, cliente=cliente,
                           NOTE_TIPI=NOTE_TIPI, NOTE_SOTTOTIPI=NOTE_SOTTOTIPI,
                           NOTE_PRIORITA=NOTE_PRIORITA)


@app.route("/cliente/<int:cliente_id>/note/aggiungi", methods=["POST"])
def note_aggiungi_da_cliente(cliente_id):
    """Aggiunta rapida di una nota dalla scheda cliente."""
    dati = request.form.to_dict()
    dati["cliente_id"] = str(cliente_id)
    if (dati.get("testo") or "").strip():
        _crea_nota(dati)  # _crea_nota usa solo .get(), un dict basta
    return redirect(url_for("cliente_dettaglio", cliente_id=cliente_id))


@app.route("/note/<int:nota_id>/completata", methods=["POST"])
def note_completata(nota_id):
    """Segna/desegna una nota come completata."""
    completa = request.form.get("completa", "1") == "1"
    nuovo_stato = "Completata" if completa else "Aperta"
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE note SET completata = {_PH}, stato = {_PH} WHERE id = {_PH}",
            (completa, nuovo_stato, nota_id),
        )
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "completata": completa})
    return redirect(request.form.get("torna") or url_for("note_inbox"))


@app.route("/note/<int:nota_id>/elimina", methods=["POST"])
def note_elimina(nota_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM note WHERE id = {_PH}", (nota_id,))
    return redirect(request.form.get("torna") or url_for("note_inbox"))


@app.route("/api/note/suggerisci")
def api_note_suggerisci():
    """Autocomplete del nominativo. Unisce due fonti per accelerare l'inserimento:
      1) i clienti del gestionale (selezionandoli la nota si collega al cliente);
      2) i nominativi già usati in note precedenti (riuso rapido, nota libera).
    Così, salvando le note mano a mano, i nomi ricorrenti si suggeriscono da soli."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify([])
    like = f"%{q}%"
    out, visti = [], set()
    with get_db() as conn:
        cur = conn.cursor()
        # 1) Clienti in anagrafica
        cur.execute(
            f"""SELECT id, cognome, nome, codice_fiscale FROM clienti
                WHERE cognome LIKE {_PH} OR nome LIKE {_PH} OR codice_fiscale LIKE {_PH}
                ORDER BY cognome, nome LIMIT 8""",
            (like, like, like),
        )
        for r in cur.fetchall():
            nome = f"{r['cognome']} {r['nome']}".strip()
            visti.add(nome.lower())
            out.append({
                "tipo": "cliente", "id": r["id"], "nominativo": nome,
                "label": nome + (f" — {r['codice_fiscale']}" if r["codice_fiscale"] else ""),
            })
        # 2) Nominativi già scritti in note precedenti (non duplicare i clienti)
        cur.execute(
            f"""SELECT DISTINCT nominativo FROM note
                WHERE nominativo <> '' AND nominativo LIKE {_PH}
                ORDER BY nominativo LIMIT 8""",
            (like,),
        )
        for r in cur.fetchall():
            nome = (r["nominativo"] or "").strip()
            if nome and nome.lower() not in visti:
                visti.add(nome.lower())
                out.append({"tipo": "nominativo", "id": None,
                            "nominativo": nome, "label": nome})
    return jsonify(out[:12])


def _IS_POSTGRES_NOTE() -> bool:
    """True se il DB è PostgreSQL (per il dialetto data nelle query note)."""
    return _DATE_FILTER.startswith("TO_CHAR")


# ── Modulo pubblico per i pazienti (senza login) ─────────────────────────────
# Campi che il paziente compila da solo: sola anagrafica di base. ASL, centro,
# medico e il resto li completa l'operatore in fase di verifica.
_MODULO_PAZIENTE_FIELDS = [
    "cognome", "nome", "codice_fiscale", "data_nascita", "luogo_nascita",
    "residenza_via", "residenza_civico", "residenza_citta", "provincia",
    "residenza_cap", "residente_dal_anno", "telefono", "email",
    "documento_tipo_numero", "documento_rilascio_luogo", "documento_data_rilascio",
]
# Tutti obbligatori tranne l'email.
_MODULO_PAZIENTE_OBBLIGATORI = [c for c in _MODULO_PAZIENTE_FIELDS if c != "email"]


@app.route("/modulo-paziente", methods=["GET", "POST"])
def modulo_paziente():
    """Modulo pubblico (link condivisibile, niente login) che i pazienti
    compilano da soli. L'invio crea un cliente con flag `da_verificare`: arriva
    nell'anagrafica ma evidenziato come 'da verificare', l'operatore lo controlla."""
    if request.method == "POST":
        # Honeypot anti-bot: campo nascosto che un umano lascia vuoto.
        if (request.form.get("azienda") or "").strip():
            return render_template("modulo_paziente.html", inviato=True, cliente={}, errore=None)
        dati = _leggi_cliente_dal_form(request.form)
        if any(not dati.get(c) for c in _MODULO_PAZIENTE_OBBLIGATORI):
            return render_template("modulo_paziente.html", cliente=dati, inviato=False,
                                   errore="Per favore compila tutti i campi obbligatori (contrassegnati con *).")
        if not request.form.get("consenso"):
            return render_template("modulo_paziente.html", cliente=dati, inviato=False,
                                   errore="Per inviare devi acconsentire al trattamento dei dati.")
        if not dati.get("note"):
            dati["note"] = f"Inviato dal modulo paziente il {date.today().isoformat()}"
        cols = CLIENTE_FIELDS + ["da_verificare"]
        ph = ", ".join([_PH] * len(cols))
        valori = tuple(dati[c] for c in CLIENTE_FIELDS) + (True,)
        try:
            with get_db() as conn:
                cur = conn.cursor()
                cur.execute(f"INSERT INTO clienti ({', '.join(cols)}) VALUES ({ph})", valori)
        except Exception:
            import sys, traceback
            traceback.print_exc(file=sys.stderr)
            return render_template(
                "modulo_paziente.html", cliente=dati, inviato=False,
                errore="C'è stato un problema tecnico nel salvataggio. Riprova tra poco "
                       "oppure inviaci i dati su WhatsApp al 06 56567542.",
            )
        return render_template("modulo_paziente.html", inviato=True, cliente={}, errore=None)
    return render_template("modulo_paziente.html", cliente={}, inviato=False, errore=None)


@app.route("/cliente/<int:cliente_id>/verificato", methods=["POST"])
def cliente_verificato(cliente_id):
    """Toglie il flag 'da verificare' a un cliente arrivato dal modulo pubblico."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE clienti SET da_verificare = {_PH} WHERE id = {_PH}", (False, cliente_id))
    return redirect(request.form.get("torna") or url_for("cliente_dettaglio", cliente_id=cliente_id))


@app.route("/cliente/<int:cliente_id>")
def cliente_dettaglio(cliente_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM clienti WHERE id = {_PH}", (cliente_id,))
        cliente = cur.fetchone()
        if not cliente:
            return "Cliente non trovato", 404
        cur.execute(
            f"""SELECT p.*, COALESCE(SUM(pr.importo), 0) AS costo_totale
                FROM pratiche p
                LEFT JOIN preventivi pr ON pr.pratica_id = p.id
                WHERE p.cliente_id = {_PH}
                GROUP BY p.id
                ORDER BY p.data_pratica DESC""",
            (cliente_id,),
        )
        pratiche = cur.fetchall()
        cur.execute(
            f"""SELECT * FROM note
                WHERE cliente_id = {_PH}
                ORDER BY completata ASC, COALESCE(scadenza, '9999-12-31') ASC, creato_il DESC""",
            (cliente_id,),
        )
        note = cur.fetchall()
    return render_template("cliente_dettaglio.html", cliente=cliente,
                           pratiche=pratiche, note=note,
                           NOTE_TIPI=NOTE_TIPI, NOTE_PRIORITA=NOTE_PRIORITA)


@app.route("/cliente/<int:cliente_id>/modifica", methods=["GET", "POST"])
def cliente_modifica(cliente_id):
    if request.method == "POST":
        dati = _leggi_cliente_dal_form(request.form)
        if not dati["cognome"]:
            dati["id"] = cliente_id
            return render_template("cliente_form.html", cliente=dati, errore="Il cognome è obbligatorio.", modifica=True, centri=opzioni_centri(), asl_opzioni=opzioni_asl())
        set_clause = ", ".join(f"{c} = {_PH}" for c in CLIENTE_FIELDS)
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE clienti SET {set_clause} WHERE id = {_PH}",
                tuple(dati[c] for c in CLIENTE_FIELDS) + (cliente_id,),
            )
        return redirect(url_for("cliente_dettaglio", cliente_id=cliente_id))

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM clienti WHERE id = {_PH}", (cliente_id,))
        cliente = cur.fetchone()
        if not cliente:
            return "Cliente non trovato", 404
    return render_template("cliente_form.html", cliente=cliente, errore=None, modifica=True, centri=opzioni_centri(), asl_opzioni=opzioni_asl())


@app.route("/cliente/<int:cliente_id>/elimina", methods=["POST"])
def cliente_elimina(cliente_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) AS n FROM pratiche WHERE cliente_id = {_PH}", (cliente_id,))
        n = cur.fetchone()["n"]
        if n > 0:
            # Non eliminare un cliente con pratiche collegate: si perderebbe il legame.
            return redirect(url_for("cliente_dettaglio", cliente_id=cliente_id))
        cur.execute(f"DELETE FROM clienti WHERE id = {_PH}", (cliente_id,))
    return redirect(url_for("clienti"))


# ── API: ricerca clienti (per selettore in nuova pratica) ─────────────────────

@app.route("/api/estrai-cliente", methods=["POST"])
def api_estrai_cliente():
    """Estrae i campi anagrafici da un messaggio in testo libero (Claude API)."""
    testo = (request.form.get("testo") or "").strip()
    if not testo and request.is_json:
        testo = ((request.get_json(silent=True) or {}).get("testo") or "").strip()
    if not testo:
        return jsonify({"ok": False, "errore": "Testo vuoto"}), 400
    try:
        from ai_extract import estrai_dati_cliente
        dati = estrai_dati_cliente(testo, opzioni_centri(), opzioni_asl())
        return jsonify({"ok": True, "dati": dati})
    except RuntimeError as e:
        # Chiave non configurata
        return jsonify({"ok": False, "errore": str(e)}), 503
    except Exception:
        app.logger.exception("Estrazione cliente fallita")
        return jsonify({"ok": False, "errore": "Estrazione non riuscita"}), 500


@app.route("/api/clienti")
def api_clienti():
    q = (request.args.get("q") or "").strip()
    with get_db() as conn:
        cur = conn.cursor()
        if q:
            like = f"%{q}%"
            cur.execute(
                f"""SELECT id, cognome, nome, codice_fiscale, asl, medico_curante FROM clienti
                    WHERE cognome LIKE {_PH} OR nome LIKE {_PH} OR codice_fiscale LIKE {_PH}
                    ORDER BY cognome, nome LIMIT 20""",
                (like, like, like),
            )
        else:
            cur.execute(
                "SELECT id, cognome, nome, codice_fiscale, asl, medico_curante FROM clienti "
                "ORDER BY cognome, nome LIMIT 20"
            )
        risultati = [dict(r) for r in cur.fetchall()]
    return jsonify(risultati)


# ── Backup dati ───────────────────────────────────────────────────────────────

@app.route("/backup/scarica")
def scarica_backup():
    """Scarica un backup completo (tutte le tabelle) come file JSON."""
    import backup as backup_mod
    payload = backup_mod.dump_json()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=backup_{ts}.json"},
    )


# ── Avvio ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n✓ Gestionale Marginalità avviato")
    print("  Apri il browser su: http://localhost:5001\n")
    app.run(debug=True, port=5001)
