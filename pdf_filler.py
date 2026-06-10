"""
Compilazione moduli PDF (PDF in uscita).

Riceve i dati di una pratica + cliente e restituisce i byte di un PDF AcroForm
compilato, pronto per il download. Non conosce la UI: in ingresso dict, in uscita bytes.

I nomi dei campi PDF sono la fonte di verità in assets/pdf-templates/pdf_fields.json
(rigenerabile con scripts/dump_pdf_fields.py).
"""
import io
import os
from datetime import date, datetime

from pypdf import PdfReader, PdfWriter

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "pdf-templates")

# Registro dei moduli generabili.
#   stato: "ok"      → mappatura completa, generabile
#          "parziale"→ generabile ma alcune sezioni restano vuote (es. righe ausili)
#          "todo"    → non ancora mappato
PDF_TEMPLATES = {
    "autocert-asl-rm3": {
        "label": "Autocertificazione + Delega ASL RM3",
        "file": "autocert-asl-rm3.pdf",
        "stato": "ok",
        "richiede_cliente": True,
    },
    "preventivo-sapio": {
        "label": "Preventivo Sapio Life",
        "file": "preventivo-sapio-v1.pdf",
        "stato": "ok",  # anagrafica + righe ausili + totali
        "richiede_cliente": True,
    },
    "prescrizione-gen": {
        "label": "Prescrizione presidi (Allegato 3)",
        "file": "Prescrizione Gen.pdf",
        "stato": "ok",  # anagrafica + righe ausili + significato terapeutico
        "richiede_cliente": True,
    },
}

# Numero massimo di righe ausili stampabili
_SAPIO_MAX_RIGHE = 16
_PRESCR_MAX_RIGHE = 15        # righe 0..14 sul modulo Allegato 3
_PRESCR_SIGN_RIGHE = 6        # righe del significato terapeutico
_PRESCR_SIGN_WIDTH = 95       # caratteri per riga del significato terapeutico


# ── Formattazione valori ──────────────────────────────────────────────────────

def _fmt_data(val) -> str:
    """ISO 'YYYY-MM-DD' (o date/datetime) → 'gg/mm/aaaa'. Vuoto → ''."""
    if not val:
        return ""
    if isinstance(val, (date, datetime)):
        return val.strftime("%d/%m/%Y")
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19] if "T" in s else s, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s  # formato non riconosciuto: passa così com'è


def _fmt_euro(n) -> str:
    """Numero → formato italiano '1.234,56' (senza simbolo €)."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    s = f"{v:,.2f}"            # 1,234.56 (stile US)
    return s.replace(",", "_").replace(".", ",").replace("_", ".")  # → 1.234,56


def _euro(n) -> str:
    """Importo con simbolo € in coda: '1.234,56 €'. Vuoto → ''."""
    s = _fmt_euro(n)
    return f"{s} €" if s else ""


def _fmt_qta(n) -> str:
    """Quantità: intero se senza decimali, altrimenti con la virgola."""
    try:
        v = float(n)
    except (TypeError, ValueError):
        return ""
    return str(int(v)) if v == int(v) else _fmt_euro(v)


def numero_preventivo(pratica: dict, cliente: dict = None) -> str:
    """
    Numero preventivo. Se impostato a mano sulla pratica lo usa così com'è,
    altrimenti lo genera nel formato 'AM{gg}{mm}.{aa}.{ASL}' sulla data di
    compilazione (oggi), con la sigla ASL senza spazi.
    Es. compilato il 09/06/2026, ASL 'RM 2' → 'AM0906.26.RM2'.
    """
    n = (pratica.get("numero_pratica") or "").strip()
    if n:
        return n
    oggi = date.today()
    base = f"AM{oggi.day:02d}{oggi.month:02d}.{oggi.strftime('%y')}"
    asl = "".join(_asl(pratica, cliente or {}).split()).upper()  # 'RM 2' → 'RM2'
    return f"{base}.{asl}" if asl else base


def _wrap_lines(text: str, width: int, maxlines: int) -> list:
    """Spezza un testo lungo in righe da ~width caratteri, max maxlines."""
    import textwrap
    text = (text or "").strip()
    if not text:
        return []
    return textwrap.wrap(text, width=width)[:maxlines]


def _nome_completo(cliente: dict) -> str:
    cognome = (cliente.get("cognome") or "").strip()
    nome = (cliente.get("nome") or "").strip()
    return f"{cognome} {nome}".strip()


def _via_completa(cliente: dict) -> str:
    via = (cliente.get("residenza_via") or "").strip()
    civ = (cliente.get("residenza_civico") or "").strip()
    return f"{via} {civ}".strip()


def _citta_completa(cliente: dict) -> str:
    citta = (cliente.get("residenza_citta") or "").strip()
    prov = (cliente.get("provincia") or "").strip()
    return f"{citta} ({prov})" if (citta and prov) else citta


def _asl(pratica: dict, cliente: dict) -> str:
    return (pratica.get("asl_destinataria") or cliente.get("asl") or "").strip()


# ── Costruzione field map per template ────────────────────────────────────────

def build_field_map(template_id: str, pratica: dict, cliente: dict, righe: list = None) -> dict:
    cliente = cliente or {}
    pratica = pratica or {}
    righe = righe or []
    oggi = date.today().strftime("%d/%m/%Y")

    if template_id == "autocert-asl-rm3":
        nome = _nome_completo(cliente)
        recapiti = (cliente.get("telefono") or "").strip()
        if cliente.get("email"):
            recapiti = f"{recapiti}  {cliente['email']}".strip()
        return {
            # Autocertificazione
            "autocert_asl": _asl(pratica, cliente),
            "autocert_sottoscritto": nome,
            "autocert_codice_fiscale": (cliente.get("codice_fiscale") or "").strip(),
            "autocert_recapiti": recapiti,
            "autocert_medico_struttura": (pratica.get("medico_struttura") or "").strip(),
            "autocert_data_prescrizione": _fmt_data(pratica.get("data_pratica")),
            "autocert_nato_data": _fmt_data(cliente.get("data_nascita")),
            "autocert_nato_luogo": (cliente.get("luogo_nascita") or "").strip(),
            "autocert_residente_via": _via_completa(cliente),
            "autocert_residente_citta": _citta_completa(cliente),
            "autocert_decorrenza_residenza_data": _fmt_data(cliente.get("decorrenza_residenza")),
            "autocert_luogo_data": f"Roma, {oggi}",
            # Delega RM3 (delegante = il cliente)
            "delega_rm3_dichiarante_nome": nome,
            "delega_rm3_dichiarante_nato_luogo": (cliente.get("luogo_nascita") or "").strip(),
            "delega_rm3_dichiarante_provincia": (cliente.get("provincia") or "").strip(),
            "delega_rm3_dichiarante_nato_data": _fmt_data(cliente.get("data_nascita")),
            "delega_rm3_dichiarante_residente_comune": (cliente.get("residenza_citta") or "").strip(),
            "delega_rm3_dichiarante_residente_via": _via_completa(cliente),
            "delega_rm3_documento_tipo_numero": (cliente.get("documento_tipo_numero") or "").strip(),
            "delega_rm3_documento_data_rilascio": _fmt_data(cliente.get("documento_data_rilascio")),
            "delega_rm3_oggetto_richiesta": (pratica.get("ausilio") or "").strip(),
            "delega_rm3_data_firma": oggi,
            "delega_rm3_data_consenso": oggi,
        }

    if template_id == "preventivo-sapio":
        fm = {
            "preventivo_assistito": _nome_completo(cliente),
            "preventivo_nato_luogo": (cliente.get("luogo_nascita") or "").strip(),
            "preventivo_nato_data": _fmt_data(cliente.get("data_nascita")),
            # ATTENZIONE: nel template Sapio i due campi sono invertiti rispetto al
            # nome → il campo *_citta è la riga "RESIDENTE IN:" (in alto, l'indirizzo),
            # *_via è la riga sottostante (il comune). Riempiamo di conseguenza.
            "preventivo_residente_citta": _via_completa(cliente),   # riga "RESIDENTE IN:" = indirizzo
            "preventivo_residente_via": _citta_completa(cliente),    # riga sotto = comune (prov)
            "preventivo_telefono": (cliente.get("telefono") or "").strip(),
            "preventivo_asl": _asl(pratica, cliente),
            "preventivo_data": oggi,                                 # data di compilazione del modulo
            "preventivo_numero": numero_preventivo(pratica, cliente),
            "preventivo_ref_struttura": (pratica.get("medico_struttura") or "").strip(),
        }
        # Righe e totali NON vanno nell'AcroForm: vengono disegnati con un overlay
        # uniforme (vedi _overlay_preventivo_tabella) perché le celle del template
        # hanno altezze diverse e il viewer le centra in modo incoerente.
        return fm

    if template_id == "prescrizione-gen":
        fm = {
            "Cognome": (cliente.get("cognome") or "").strip(),
            "Nome": (cliente.get("nome") or "").strip(),
            "Data Nascita": _fmt_data(cliente.get("data_nascita")),
            "Luogo Nasc": (cliente.get("luogo_nascita") or "").strip(),
            "Resid. via": _via_completa(cliente),
            "Comune Res": (cliente.get("residenza_citta") or "").strip(),
            "Provinc": (cliente.get("provincia") or "").strip(),
            "C.F": (cliente.get("codice_fiscale") or "").strip(),
            "Telefono": (cliente.get("telefono") or "").strip(),
            "Patologia": (pratica.get("diagnosi") or "").strip(),
        }
        # Righe ausili (0..14). La riga 0 ha il campo ISO con nome annidato extra.
        for i, r in enumerate(righe[:_PRESCR_MAX_RIGHE]):
            iso_field = "Cod. ISO.0.0.0.0" if i == 0 else f"Cod. ISO.{i}.0"
            fm[f"Q.tà.{i}.0"] = _fmt_qta(r.get("qta") or 0)
            fm[f"Descrizione LEA.{i}.0"] = (r.get("descrizione") or "").strip()
            fm[iso_field] = (r.get("codice_iso") or "").strip()
        # Significato terapeutico: testo lungo spezzato su max 6 righe
        for i, riga in enumerate(_wrap_lines(pratica.get("sign_terapeutico"),
                                             _PRESCR_SIGN_WIDTH, _PRESCR_SIGN_RIGHE)):
            fm[f"Signf. Terapeutico.{i}.0"] = riga
        return fm

    raise ValueError(f"Template sconosciuto: {template_id}")


# ── Stile dei campi (font e allineamento) ─────────────────────────────────────

# Campi (per sottostringa nel nome) da centrare orizzontalmente: importi e q.tà
_CENTER_HINTS = ("prezzo_unitario", "prezzo_totale", "_qta", "totale_imponibile",
                 "preventivo_iva", "totale_lordo")


def _restyle_form_fields(writer, filled_names: set, center_hints=(), font_size: int = 11):
    """
    Migliora la resa dei campi compilati:
    - font a dimensione fissa più leggibile (default 11pt nel /DA)
    - allineamento orizzontale centrato (/Q=1) per i campi indicati in center_hints
    - rimuove l'appearance stream esistente (/AP) così il viewer la rigenera con
      il nuovo stile (insieme a NeedAppearances)
    """
    import re
    from pypdf.generic import NameObject, NumberObject, TextStringObject

    for page in writer.pages:
        for a in (page.get("/Annots") or []):
            o = a.get_object()
            nm = str(o.get("/T") or "")
            if not nm or nm not in filled_names:
                continue
            da = o.get("/DA")
            if da:
                new_da = re.sub(r"(/[A-Za-z0-9]+)\s+[\d.]+\s+Tf", rf"\1 {font_size} Tf", str(da))
                o[NameObject("/DA")] = TextStringObject(new_da)
            if any(h in nm for h in center_hints):
                o[NameObject("/Q")] = NumberObject(1)
            if "/AP" in o:
                del o[NameObject("/AP")]


# ── Overlay tabella preventivo (resa uniforme) ────────────────────────────────

def _field_rects(reader) -> dict:
    """{nome_qualificato: (x0, y0, x1, y1)} di tutti i widget della prima pagina."""
    def qn(o):
        parts, cur = [], o
        while cur is not None:
            t = cur.get("/T")
            if t is not None:
                parts.append(str(t))
            p = cur.get("/Parent")
            cur = p.get_object() if p else None
        return ".".join(reversed(parts))

    rects = {}
    for a in (reader.pages[0].get("/Annots") or []):
        o = a.get_object()
        r = o.get("/Rect")
        if r is None:
            continue
        rects[qn(o)] = tuple(float(v) for v in r)
    return rects


def _draw_fit(c, text, x0, x1, baseline, align="left", size=9, font="Helvetica", min_size=6.0):
    """Disegna testo dentro [x0,x1] alla baseline data, riducendo il corpo se non entra."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    if not text:
        return
    max_w = (x1 - x0) - 4
    s = size
    while s > min_size and stringWidth(text, font, s) > max_w:
        s -= 0.5
    c.setFont(font, s)
    if align == "center":
        w = stringWidth(text, font, s)
        c.drawString(x0 + (x1 - x0 - w) / 2, baseline, text)
    elif align == "right":
        c.drawRightString(x1 - 2, baseline, text)
    else:
        c.drawString(x0 + 2, baseline, text)


def _overlay_preventivo_tabella(reader, righe, iva_pct, size=9):
    """Crea una pagina-overlay con righe e totali del preventivo, font uniforme
    e baseline allineata in basso per ogni riga. Restituisce la pagina pypdf."""
    import io as _io
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader as _PdfReader

    rects = _field_rects(reader)
    box = reader.pages[0].mediabox
    W, H = float(box.width), float(box.height)
    buf = _io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))

    imponibile = 0.0
    for i, r in enumerate(righe[:_SAPIO_MAX_RIGHE]):
        n = i + 1
        pref = f"preventivo_riga{n:02d}"
        desc_name = f"{pref}_descrizione.0.0" if n == 1 else f"{pref}_descrizione"
        if desc_name not in rects:
            continue
        qta = r.get("qta") or 0
        prezzo = r.get("prezzo_unitario") or 0
        totale = qta * prezzo
        imponibile += totale
        # baseline comune alla riga = bordo inferiore della cella descrizione + 4
        base = rects[desc_name][1] + 4
        def cell(name, text, align):
            if name in rects:
                x0, _, x1, _ = rects[name]
                _draw_fit(c, text, x0, x1, base, align, size)
        cell(f"{pref}_iso", (r.get("codice_iso") or "").strip(), "left")
        cell(desc_name, (r.get("descrizione") or "").strip(), "left")
        cell(f"{pref}_qta", _fmt_qta(qta), "center")
        cell(f"{pref}_prezzo_unitario", _euro(prezzo), "right")
        cell(f"{pref}_prezzo_totale", _euro(totale), "right")

    iva = imponibile * (iva_pct / 100.0)
    for name, val in (
        ("preventivo_totale_imponibile", _euro(imponibile)),
        ("preventivo_iva", _euro(iva)),
        ("preventivo_totale_lordo", _euro(imponibile + iva)),
    ):
        if name in rects:
            x0, y0, x1, y1 = rects[name]
            _draw_fit(c, val, x0, x1, y0 + 3, "right", size)

    c.save()
    buf.seek(0)
    return _PdfReader(buf).pages[0]


# ── Generazione PDF ───────────────────────────────────────────────────────────

def compila_pdf(template_id: str, pratica: dict, cliente: dict, righe: list = None) -> bytes:
    tpl = PDF_TEMPLATES.get(template_id)
    if not tpl:
        raise ValueError(f"Template sconosciuto: {template_id}")

    path = os.path.join(TEMPLATES_DIR, tpl["file"])
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File template mancante: {path}")

    field_map = build_field_map(template_id, pratica, cliente, righe)
    # Scarta i valori vuoti: non serve riscriverli e si evita di azzerare default
    field_map = {k: v for k, v in field_map.items() if v not in ("", None)}

    reader = PdfReader(path)
    writer = PdfWriter()
    writer.append(reader)

    for page in writer.pages:
        writer.update_page_form_field_values(page, field_map)

    # Migliora font sui campi compilati (intestazione)
    _restyle_form_fields(writer, set(field_map.keys()), center_hints=_CENTER_HINTS)

    # Preventivo Sapio: righe e totali resi con overlay uniforme (font e
    # allineamento coerenti, indipendenti dalla resa del viewer)
    if template_id == "preventivo-sapio" and righe:
        iva_pct = pratica.get("iva_percentuale")
        iva_pct = 4.0 if iva_pct in (None, "") else float(iva_pct)
        try:
            overlay = _overlay_preventivo_tabella(reader, righe, iva_pct)
            writer.pages[0].merge_page(overlay)
        except Exception as _ov_err:
            import sys
            print("WARN overlay preventivo non riuscito:", _ov_err, file=sys.stderr)

    # NeedAppearances: forza i viewer a rigenerare l'aspetto con il nuovo stile
    try:
        writer.set_need_appearances_writer(True)
    except Exception:
        pass

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def nome_file_consigliato(template_id: str, pratica: dict, cliente: dict) -> str:
    """Es. 'AM0105.26 - ROSSI MARIO - Autocertificazione ASL RM3.pdf'."""
    tpl = PDF_TEMPLATES.get(template_id, {})
    numero = numero_preventivo(pratica or {}, cliente) or f"pratica-{(pratica or {}).get('id', '')}"
    nome = _nome_completo(cliente or {}).upper() or "CLIENTE"
    label = tpl.get("label", template_id)
    base = f"{numero} - {nome} - {label}".strip(" -")
    # rimuove caratteri problematici nei filename
    for ch in '/\\:*?"<>|':
        base = base.replace(ch, "-")
    return base + ".pdf"
