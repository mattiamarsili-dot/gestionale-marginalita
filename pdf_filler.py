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
# Ordine delle categorie nell'elenco moduli: prima i preventivi, poi le deleghe,
# infine prescrizioni e autocertificazioni.
CATEGORIA_ORDINE = {"preventivo": 0, "delega": 1, "prescrizione": 2, "autocert": 3}

PDF_TEMPLATES = {
    "preventivo-sapio": {
        "label": "Preventivo Sapio Life",
        "file": "preventivo-sapio-v1.pdf",
        "stato": "ok",  # anagrafica + righe ausili + totali
        "richiede_cliente": True,
        "categoria": "preventivo",
        "sempre_attivo": True,
    },
    "preventivo": {
        "label": "Preventivo generico",
        "file": "Preventivo.pdf",
        "stato": "ok",  # anagrafica + tabella ausili + totali (campi AcroForm dedicati)
        "richiede_cliente": True,
        "categoria": "preventivo",
        "sempre_attivo": True,
    },
    "delega-rm2": {
        "label": "Delega ASL RM2",
        "file": "Delega RM2.pdf",
        "stato": "ok",  # delegante (cliente) + dati pratica
        "richiede_cliente": True,
        "categoria": "delega",
    },
    "delega-generica": {
        "label": "Autocertificazione + Delega generica",
        "file": "Delega Generica.pdf",
        "stato": "ok",  # stessa famiglia campi di autocert-asl-rm3
        "richiede_cliente": True,
        "categoria": "delega",
    },
    "prescrizione-gen": {
        "label": "Prescrizione presidi (Allegato 3)",
        "file": "Prescrizione Gen.pdf",
        "stato": "ok",  # anagrafica + righe ausili + significato terapeutico
        "richiede_cliente": True,
        "categoria": "prescrizione",
    },
    "prescrizione-hbg": {
        "label": "Prescrizione HBG",
        "file": "Prescrizione HBG.pdf",
        "stato": "ok",  # anagrafica + righe (iso/qtà) + significato terapeutico
        "richiede_cliente": True,
        "categoria": "prescrizione",
    },
    "prescrizione-santalucia": {
        "label": "Prescrizione Santa Lucia",
        "file": "PrescrizioneSanta lucia.pdf",
        "stato": "ok",  # anagrafica (field*_1/Text1 per posizione) + righe + significato
        "richiede_cliente": True,
        "categoria": "prescrizione",
    },
    "autocert-asl-rm3": {
        "label": "Autocertificazione + Delega ASL RM3",
        "file": "autocert-asl-rm3.pdf",
        "stato": "ok",
        "richiede_cliente": True,
        "categoria": "autocert",
    },
}

# Moduli sempre attivi sulla pratica (non disattivabili): i preventivi.
MODULI_SEMPRE_ATTIVI = {tid for tid, m in PDF_TEMPLATES.items() if m.get("sempre_attivo")}


def moduli_ordinati() -> list:
    """Lista dei moduli (con id) ordinati per categoria: preventivi → deleghe → resto."""
    items = [{"id": tid, **meta} for tid, meta in PDF_TEMPLATES.items()]
    items.sort(key=lambda m: (CATEGORIA_ORDINE.get(m.get("categoria"), 9), m["label"]))
    return items

# Dimensione font unica per tutti i campi compilati (i template sono nativamente
# Arial 10pt: usiamo la stessa misura per il rendering /DA e per il calcolo del
# mandata a capo, così tutto il testo del modulo è coerente e non sfora le caselle).
_FORM_FONT_SIZE = 10

# Numero massimo di righe ausili stampabili per modulo
_SAPIO_MAX_RIGHE = 16
_PRESCR_MAX_RIGHE = 15        # righe 0..14 sul modulo Allegato 3
# Significato terapeutico: mandata a capo in base alla larghezza REALE del campo
# (in punti, meno ~6pt di margine interno) misurata col font, anziché a conteggio
# caratteri — così vale sia per testo minuscolo sia maiuscolo (larghezze diverse).
_PRESCR_SIGN_RIGHE = 6        # righe del significato (campo largo 521 pt)
_PRESCR_SIGN_WIDTH_PT = 515.0
_HBG_MAX_RIGHE = 16           # righe 0..15 sul modulo HBG
_HBG_SIGN_RIGHE = 16          # righe del significato HBG (campo largo 375 pt)
_HBG_SIGN_WIDTH_PT = 369.0
_SL_MAX_RIGHE = 12            # righe 0..11 sul modulo Santa Lucia
_SL_SIGN_RIGHE = 6           # righe del significato Santa Lucia (campo largo 520 pt)
_SL_SIGN_WIDTH_PT = 514.0
_PREV_MAX_RIGHE = 16         # righe 0..15 sul preventivo generico


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


def _wrap_lines_pt(text: str, width_pt: float, maxlines: int,
                   font: str = "Helvetica", size: float = 10.0) -> list:
    """Spezza il testo in righe in base alla larghezza reale del campo (in punti),
    misurando ogni riga con le metriche del font. Più affidabile del conteggio
    caratteri quando il testo mischia maiuscole/minuscole (larghezze diverse)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    text = (text or "").strip()
    if not text:
        return []

    def fits(s: str) -> bool:
        return stringWidth(s, font, size) <= width_pt

    righe, corrente = [], ""
    for parola in text.split():
        candidato = parola if not corrente else f"{corrente} {parola}"
        if fits(candidato):
            corrente = candidato
            continue
        if corrente:
            righe.append(corrente)
            corrente = ""
        # parola più lunga della riga: spezzala a forza per carattere
        while not fits(parola):
            n = len(parola)
            while n > 1 and not fits(parola[:n]):
                n -= 1
            righe.append(parola[:n])
            parola = parola[n:]
        corrente = parola
    if corrente:
        righe.append(corrente)
    return righe[:maxlines]


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


# ── Vista canonica dei dati (sorgente unica per tutti i moduli) ───────────────

def dati_canonici(pratica: dict, cliente: dict) -> dict:
    """
    Normalizza e pre-formatta tutti i dati cliente+pratica che servono ai moduli.
    Ogni template mappa solo `nome_campo_PDF → chiave_canonica`, senza ripetere
    la logica di estrazione/formattazione. Le date sono già 'gg/mm/aaaa'.
    """
    cliente = cliente or {}
    pratica = pratica or {}
    oggi = date.today().strftime("%d/%m/%Y")
    recapiti = (cliente.get("telefono") or "").strip()
    if cliente.get("email"):
        recapiti = f"{recapiti}  {cliente['email']}".strip()
    return {
        "nome":             _nome_completo(cliente),
        "cognome":          (cliente.get("cognome") or "").strip(),
        "nome_proprio":     (cliente.get("nome") or "").strip(),
        "cf":               (cliente.get("codice_fiscale") or "").strip(),
        "nato_data":        _fmt_data(cliente.get("data_nascita")),
        "nato_luogo":       (cliente.get("luogo_nascita") or "").strip(),
        "provincia":        (cliente.get("provincia") or "").strip(),
        "via":              _via_completa(cliente),     # via + civico
        "citta":            _citta_completa(cliente),   # città (prov)
        "comune":           (cliente.get("residenza_citta") or "").strip(),
        "cap":              (cliente.get("residenza_cap") or "").strip(),
        "telefono":         (cliente.get("telefono") or "").strip(),
        "email":            (cliente.get("email") or "").strip(),
        "recapiti":         recapiti,
        "asl":              _asl(pratica, cliente),
        "centro":           (cliente.get("centro") or "").strip(),
        "medico_curante":   (cliente.get("medico_curante") or "").strip(),
        # Data piena se presente, altrimenti il solo anno dal modulo paziente
        "decorrenza_residenza":    _fmt_data(cliente.get("decorrenza_residenza")) or (cliente.get("residente_dal_anno") or "").strip(),
        "documento_tipo_numero":   (cliente.get("documento_tipo_numero") or "").strip(),
        "documento_data_rilascio": _fmt_data(cliente.get("documento_data_rilascio")),
        # Tutore legale (= delegato delle deleghe)
        "ha_tutore":               bool(cliente.get("ha_tutore")),
        "tutore_nome":             (cliente.get("tutore_nome") or "").strip(),
        "tutore_cf":               (cliente.get("tutore_cf") or "").strip(),
        "tutore_documento_tipo_numero":    (cliente.get("tutore_documento_tipo_numero") or "").strip(),
        "tutore_documento_rilascio_luogo": (cliente.get("tutore_documento_rilascio_luogo") or "").strip(),
        "tutore_documento_rilascio_data":  _fmt_data(cliente.get("tutore_documento_rilascio_data")),
        "data_prescrizione": _fmt_data(pratica.get("data_pratica")),
        "medico_struttura": (pratica.get("medico_struttura") or "").strip(),
        "ausilio":          (pratica.get("ausilio") or "").strip(),
        "diagnosi":         (pratica.get("diagnosi") or "").strip(),
        "sign_terapeutico": (pratica.get("sign_terapeutico") or "").strip(),
        "oggi":             oggi,
        "luogo_data":       f"Roma, {oggi}",
        "numero_preventivo": numero_preventivo(pratica, cliente),
    }


def _mappa_righe(righe, max_n, *, iso=None, descrizione=None, qta=None,
                 prezzo_unitario=None, prezzo_totale=None) -> dict:
    """
    Mappa le righe ausili sui campi AcroForm. Ogni colonna è opzionale e riceve
    una funzione `i → nome_campo` (i pattern di indice variano fra i moduli).
    Restituisce {nome_campo: valore_formattato}.
    """
    fm = {}
    for i, r in enumerate(righe[:max_n]):
        q = r.get("qta") or 0
        p = r.get("prezzo_unitario") or 0
        if iso:             fm[iso(i)] = (r.get("codice_iso") or "").strip()
        if descrizione:     fm[descrizione(i)] = (r.get("descrizione") or "").strip()
        if qta:             fm[qta(i)] = _fmt_qta(q)
        if prezzo_unitario: fm[prezzo_unitario(i)] = _euro(p)
        if prezzo_totale:   fm[prezzo_totale(i)] = _euro(q * p)
    return fm


# ── Costruzione field map per template ────────────────────────────────────────

def build_field_map(template_id: str, pratica: dict, cliente: dict, righe: list = None) -> dict:
    righe = righe or []
    D = dati_canonici(pratica, cliente)

    if template_id == "autocert-asl-rm3":
        return {
            # Autocertificazione
            "autocert_asl": D["asl"],
            "autocert_sottoscritto": D["nome"],
            "autocert_codice_fiscale": D["cf"],
            "autocert_recapiti": D["recapiti"],
            "autocert_medico_struttura": D["medico_struttura"],
            "autocert_data_prescrizione": D["data_prescrizione"],
            "autocert_nato_data": D["nato_data"],
            "autocert_nato_luogo": D["nato_luogo"],
            "autocert_residente_via": D["via"],
            "autocert_residente_citta": D["citta"],
            "autocert_decorrenza_residenza_data": D["decorrenza_residenza"],
            "autocert_luogo_data": D["luogo_data"],
            # Delega RM3 (delegante = il cliente)
            "delega_rm3_dichiarante_nome": D["nome"],
            "delega_rm3_dichiarante_nato_luogo": D["nato_luogo"],
            "delega_rm3_dichiarante_provincia": D["provincia"],
            "delega_rm3_dichiarante_nato_data": D["nato_data"],
            "delega_rm3_dichiarante_residente_comune": D["comune"],
            "delega_rm3_dichiarante_residente_via": D["via"],
            "delega_rm3_documento_tipo_numero": D["documento_tipo_numero"],
            "delega_rm3_documento_data_rilascio": D["documento_data_rilascio"],
            "delega_rm3_oggetto_richiesta": D["ausilio"],
            "delega_rm3_data_firma": D["oggi"],
            "delega_rm3_data_consenso": D["oggi"],
        }

    if template_id == "delega-generica":
        # Stessa famiglia di campi di autocert-asl-rm3, con qualche extra.
        # Il blocco "delegato" (feild1_1..feild14_1) lo compila a mano l'operatore.
        return {
            "autocert_sottoscritto": D["nome"],
            "autocert_codice_fiscale": D["cf"],
            "autocert_asl": D["asl"],
            "autocert_recapiti": D["recapiti"],
            "autocert_medico_struttura": D["medico_struttura"],
            "autocert_data_prescrizione": D["data_prescrizione"],
            "autocert_nato_data": D["nato_data"],
            "autocert_nato_luogo": D["nato_luogo"],
            "autocert_residente_via": D["via"],
            "autocert_residente_citta": D["citta"],
            "autocert_decorrenza_residenza_data": D["decorrenza_residenza"],
            "autocert_luogo_data": D["luogo_data"],
            "autocert_data": D["oggi"],
            "autocert_numero_preventivo": D["numero_preventivo"],
            "Autocert_ausilio": D["ausilio"],
            "delega_rm3_dichiarante_nome": D["nome"],
            "delega_rm3_dichiarante_nato_luogo": D["nato_luogo"],
            "delega_rm3_dichiarante_provincia": D["provincia"],
            "delega_rm3_dichiarante_nato_data": D["nato_data"],
            "delega_rm3_dichiarante_residente_comune": D["comune"],
            "delega_rm3_dichiarante_residente_via": D["via"],
            "delega_rm3_documento_tipo_numero": D["documento_tipo_numero"],
            "delega_rm3_documento_data_rilascio": D["documento_data_rilascio"],
            "delega_rm3_oggetto_richiesta": D["ausilio"],
            "delega_rm3_data_firma": D["oggi"],
            "delega_rm3_data_consenso": D["oggi"],
        }

    if template_id == "delega-rm2":
        # delegante = il cliente; delegato = il tutore legale (se presente),
        # altrimenti il blocco delegato resta vuoto e si compila a mano.
        return {
            "delega_rm2_delegato_documento_tipo_numero":    D["tutore_documento_tipo_numero"],
            "delega_rm2_delegato_documento_rilascio_luogo": D["tutore_documento_rilascio_luogo"],
            "delega_rm2_delegato_documento_rilascio_data":  D["tutore_documento_rilascio_data"],
            "delega_rm2_delegante_cognome_nome": D["nome"],
            "delega_rm2_delegante_cf": D["cf"],
            "delega_rm2_delegante_nato_luogo": D["nato_luogo"],
            "delega_rm2_delegante_nato_data": D["nato_data"],
            "delega_rm2_delegante_residente_citta": D["citta"],
            "delega_rm2_delegante_residente_via": D["via"],
            "delega_rm2_delegante_residenza_data": D["decorrenza_residenza"],
            "delega_rm2_delegante_telefono_email": D["recapiti"],
            "delega_rm2_delegante_documento_tipo_numero": D["documento_tipo_numero"],
            "delega_rm2_delegante_documento_rilascio_data": D["documento_data_rilascio"],
            "delega_rm2_delegante_Medico_strttura": D["medico_struttura"],  # refuso nel template
            "delega_rm2_delegante_ausilio": D["ausilio"],
            "delega_rm2_delegante_data_prescrizione": D["data_prescrizione"],
            "delega_rm2_data_firma": D["oggi"],
        }

    if template_id == "preventivo-sapio":
        # Righe e totali NON vanno nell'AcroForm: vengono disegnati con un overlay
        # uniforme (vedi _overlay_preventivo) perché le celle del template hanno
        # altezze diverse e il viewer le centra in modo incoerente.
        return {
            "preventivo_assistito": D["nome"],
            "preventivo_nato_luogo": D["nato_luogo"],
            "preventivo_nato_data": D["nato_data"],
            # ATTENZIONE: nel template Sapio i due campi sono invertiti rispetto al
            # nome → *_citta è la riga "RESIDENTE IN:" (indirizzo), *_via è il comune.
            "preventivo_residente_citta": D["via"],
            "preventivo_residente_via": D["citta"],
            "preventivo_telefono": D["telefono"],
            "preventivo_asl": D["asl"],
            "preventivo_data": D["oggi"],
            "preventivo_numero": D["numero_preventivo"],
            "preventivo_ref_struttura": D["medico_struttura"],
        }

    if template_id == "preventivo":
        # Preventivo generico: campi AcroForm dedicati per ogni cella → riempimento
        # diretto (niente overlay). Totali calcolati dalle righe.
        fm = {
            "Cognome nome": D["nome"],
            "Data Nascita": D["nato_data"],
            "Luogo Nascita": D["nato_luogo"],
            "Ind. Residenza": D["via"],
            "Città residenziali": D["citta"],
            "ASL appart": D["asl"],
            "Cellulare": D["telefono"],
            "Centro": D["centro"],
            "N. Preventivo": D["numero_preventivo"],
            "Data": D["oggi"],
        }
        fm.update(_mappa_righe(
            righe, _PREV_MAX_RIGHE,
            iso=lambda i: f"Codici ISO.0.{i}.0",
            descrizione=lambda i: f"Descrizione.0.{i}.0",
            qta=lambda i: f"Q.tà.{i}.0",
            prezzo_unitario=lambda i: f"Prezzo Uni.{i}.0",
            prezzo_totale=lambda i: f"Prezzo Tot.{i}.0",
        ))
        imponibile = sum((r.get("qta") or 0) * (r.get("prezzo_unitario") or 0)
                         for r in righe[:_PREV_MAX_RIGHE])
        iva_pct = pratica.get("iva_percentuale")
        iva_pct = 4.0 if iva_pct in (None, "") else float(iva_pct)
        iva = imponibile * (iva_pct / 100.0)
        fm["Tot. Imponib"] = _euro(imponibile)
        fm["Iva"] = _euro(iva)
        fm["Tot. Lordo"] = _euro(imponibile + iva)
        return fm

    if template_id == "prescrizione-gen":
        fm = {
            "Cognome": D["cognome"],
            "Nome": D["nome_proprio"],
            "Data Nascita": D["nato_data"],
            "Luogo Nasc": D["nato_luogo"],
            "Resid. via": D["via"],
            "Comune Res": D["comune"],
            "Provinc": D["provincia"],
            "C.F": D["cf"],
            "Telefono": D["telefono"],
            "Patologia": D["diagnosi"],
        }
        # Righe ausili (0..14). La riga 0 ha il campo ISO con nome annidato extra.
        fm.update(_mappa_righe(
            righe, _PRESCR_MAX_RIGHE,
            iso=lambda i: "Cod. ISO.0.0.0.0" if i == 0 else f"Cod. ISO.{i}.0",
            descrizione=lambda i: f"Descrizione LEA.{i}.0",
            qta=lambda i: f"Q.tà.{i}.0",
        ))
        # Significato terapeutico: testo lungo spezzato su max 6 righe, a capo
        # per larghezza reale del campo (Arial 10pt) così non sfora il bordo.
        for i, riga in enumerate(_wrap_lines_pt(D["sign_terapeutico"],
                                                _PRESCR_SIGN_WIDTH_PT, _PRESCR_SIGN_RIGHE,
                                                size=_FORM_FONT_SIZE)):
            fm[f"Signf. Terapeutico.{i}.0"] = riga
        return fm

    if template_id == "prescrizione-hbg":
        fm = {
            "prescrizione_hbg_cognome_nome": D["nome"],
            "prescrizione_hbg_nato_data": D["nato_data"],
            "prescrizione_hbg_nato_luogo": D["nato_luogo"],
            "prescrizione_hbg_provincia": D["provincia"],
            "prescrizione_hbg_provincia_CAP": D["cap"],
            "prescrizione_hbg_residente_citta": D["comune"],
            "prescrizione_hbg_residente_via": D["via"],
            "prescrizione_hbg_telefono": D["telefono"],
        }
        # Righe: solo codice ISO + quantità (nessuna colonna descrizione).
        # NB: il campo ISO ha un doppio spazio nel nome ("_iso  .{i}.0").
        fm.update(_mappa_righe(
            righe, _HBG_MAX_RIGHE,
            iso=lambda i: f"Text1prescrizione_hbg_riga01_iso  .{i}.0",
            qta=lambda i: f"prescrizione_hbg_riga01_qta.{i}.0",
        ))
        for i, riga in enumerate(_wrap_lines_pt(D["sign_terapeutico"],
                                                _HBG_SIGN_WIDTH_PT, _HBG_SIGN_RIGHE,
                                                size=_FORM_FONT_SIZE)):
            fm[f"prescrizione_hbg_sign_01.{i}.0"] = riga
        return fm

    if template_id == "prescrizione-santalucia":
        # Anagrafica su campi generici field0_1..field7_1 + Text1, identificati per
        # posizione nel modulo (riga e ordine sx→dx). NB: la diagnosi NON ha un campo
        # AcroForm su questo modulo (solo righe da scrivere a mano).
        fm = {
            "field0_1": D["cognome"],
            "field1_1": D["nome_proprio"],
            "field2_1": D["nato_data"],
            "field3_1": D["nato_luogo"],
            "field4_1": D["via"],        # Residenza Via/P.zza
            "field5_1": D["comune"],     # Comune
            "field6_1": D["provincia"],  # Prov.
            "field7_1": D["telefono"],
            "Text1": D["cf"],            # Codice Fiscale
        }
        fm.update(_mappa_righe(
            righe, _SL_MAX_RIGHE,
            iso=lambda i: f"Cod. ISO 0.0.{i}.0",
            descrizione=lambda i: f"Descrizione LEA.0.0.{i}.0",
            # quirk del template: la riga 10 ha un livello di annidamento extra
            qta=lambda i: "Q_tà.10.0.0.0" if i == 10 else f"Q_tà.{i}.0",
        ))
        for i, riga in enumerate(_wrap_lines_pt(D["sign_terapeutico"],
                                                _SL_SIGN_WIDTH_PT, _SL_SIGN_RIGHE,
                                                size=_FORM_FONT_SIZE)):
            fm[f"Sign. Terapeutico.0.{i}"] = riga
        return fm

    raise ValueError(f"Template sconosciuto: {template_id}")


# ── Stile dei campi (font e allineamento) ─────────────────────────────────────

# Campi (per sottostringa nel nome) da centrare orizzontalmente: importi e q.tà
_CENTER_HINTS = ("prezzo_unitario", "prezzo_totale", "_qta", "totale_imponibile",
                 "preventivo_iva", "totale_lordo")


def _qualified_name(o) -> str:
    """Nome qualificato del widget (concatena i /T di campo e antenati)."""
    parts, cur = [], o
    while cur is not None:
        t = cur.get("/T")
        if t is not None:
            parts.append(str(t))
        p = cur.get("/Parent")
        cur = p.get_object() if p else None
    return ".".join(reversed(parts))


def _prepara_stile_campi(writer, filled_names: set, center_hints=(), font_size: int = _FORM_FONT_SIZE):
    """
    Imposta font e allineamento sui campi DA COMPILARE, *prima* della compilazione,
    così pypdf genera l'appearance stream (/AP) già con lo stile giusto e il testo
    resta visibile in tutti i viewer (Anteprima, stampa…), senza dipendere da
    NeedAppearances:
    - /DA a dimensione font uniforme (coerente coi template nativi, 10pt)
    - /Q=1 (centrato) per i campi indicati in center_hints (importi e q.tà)
    Il match avviene sul nome QUALIFICATO, così copre anche i campi annidati
    (es. "Cod. ISO.0.0", "Signf. Terapeutico.0.0").
    """
    import re
    from pypdf.generic import NameObject, NumberObject, TextStringObject

    for page in writer.pages:
        for a in (page.get("/Annots") or []):
            o = a.get_object()
            qn = _qualified_name(o)
            if not qn or qn not in filled_names:
                continue
            da = o.get("/DA")
            if da:
                new_da = re.sub(r"(/[A-Za-z0-9]+)\s+[\d.]+\s+Tf", rf"\1 {font_size} Tf", str(da))
            else:
                new_da = f"0 0 0 rg /Helv {font_size} Tf"
            o[NameObject("/DA")] = TextStringObject(new_da)
            if any(h in qn for h in center_hints):
                o[NameObject("/Q")] = NumberObject(1)


# ── Overlay tabella preventivo (resa uniforme) ────────────────────────────────

def _field_rects(reader) -> dict:
    """{nome_qualificato: (x0, y0, x1, y1)} di tutti i widget della prima pagina."""
    rects = {}
    for a in (reader.pages[0].get("/Annots") or []):
        o = a.get_object()
        r = o.get("/Rect")
        if r is None:
            continue
        rects[_qualified_name(o)] = tuple(float(v) for v in r)
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


def _overlay_preventivo(reader, header: dict, righe, iva_pct, header_size=12, table_size=9):
    """Pagina-overlay del preventivo: intestazione (anagrafica) e tabella
    (righe + totali). Allineamenti per colonna e centratura verticale nella riga.
    L'overlay non è vincolato all'altezza delle caselle del modulo."""
    import io as _io
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader as _PdfReader

    rects = _field_rects(reader)
    box = reader.pages[0].mediabox
    W, H = float(box.width), float(box.height)
    buf = _io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))

    # ── Intestazione ─────────────────────────────────────────────────────────
    for name, val in (header or {}).items():
        if name not in rects or not val:
            continue
        x0, y0, x1, y1 = rects[name]
        if name == "preventivo_numero":
            # numero lungo → corpo ridotto per non toccare "/aus/"
            _draw_fit(c, str(val), x0, x1, y0 + 2, "left", 8.5, min_size=6)
        elif name in ("preventivo_asl", "preventivo_data"):
            # allineati in alto a destra (baseline vicino al bordo superiore)
            _draw_fit(c, str(val), x0, x1, y1 - header_size, "right", header_size, min_size=8)
        else:
            _draw_fit(c, str(val), x0, x1, y0 + 2, "left", header_size, min_size=8)

    # ── Tabella righe ──────────────────────────────────────────────────────────
    # Allineamento orizzontale per colonna; verticale: centrato nella riga
    # (uguale spazio sopra/sotto, usando la cella descrizione come banda di riga).
    col_align = {"iso": "center", "descrizione": "left", "qta": "center",
                 "prezzo_unitario": "right", "prezzo_totale": "right"}
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

        # baseline comune alla riga, centrata sulla cella q.tà (altezza standard
        # di riga): tutte le colonne risultano sulla stessa linea e centrate.
        ref = rects.get(f"{pref}_qta") or rects[desc_name]
        base = (ref[1] + ref[3]) / 2 - table_size * 0.35

        def cell(name, text, col):
            if name in rects:
                x0, _, x1, _ = rects[name]
                _draw_fit(c, text, x0, x1, base, col_align[col], table_size)
        cell(f"{pref}_iso", (r.get("codice_iso") or "").strip(), "iso")
        cell(desc_name, (r.get("descrizione") or "").strip(), "descrizione")
        cell(f"{pref}_qta", _fmt_qta(qta), "qta")
        cell(f"{pref}_prezzo_unitario", _euro(prezzo), "prezzo_unitario")
        cell(f"{pref}_prezzo_totale", _euro(totale), "prezzo_totale")

    # ── Totali (cifre a destra, centrate in verticale) ─────────────────────────
    iva = imponibile * (iva_pct / 100.0)
    for name, val in (
        ("preventivo_totale_imponibile", _euro(imponibile)),
        ("preventivo_iva", _euro(iva)),
        ("preventivo_totale_lordo", _euro(imponibile + iva)),
    ):
        if name in rects:
            x0, y0, x1, y1 = rects[name]
            _draw_fit(c, val, x0, x1, (y0 + y1) / 2 - table_size * 0.35, "right", table_size)

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

    if template_id == "preventivo-sapio":
        # Preventivo: intestazione + tabella resi interamente con overlay
        # (font uniforme, anagrafica più grande, celle centrate).
        iva_pct = pratica.get("iva_percentuale")
        iva_pct = 4.0 if iva_pct in (None, "") else float(iva_pct)
        try:
            overlay = _overlay_preventivo(reader, field_map, righe or [], iva_pct)
            writer.pages[0].merge_page(overlay)
        except Exception as _ov_err:
            import sys
            print("WARN overlay preventivo non riuscito:", _ov_err, file=sys.stderr)
    else:
        # 1) stile (font/allineamento) sui campi da compilare
        # 2) compilazione: pypdf genera l'/AP con quello stile → visibile ovunque
        _prepara_stile_campi(writer, set(field_map.keys()), center_hints=_CENTER_HINTS)
        for page in writer.pages:
            writer.update_page_form_field_values(page, field_map, auto_regenerate=False)

    # NeedAppearances come fallback: i viewer che lo onorano rigenerano dal /DA
    # (stessa dimensione), gli altri usano l'/AP già generato. In entrambi i casi
    # il testo è visibile e coerente.
    try:
        writer.set_need_appearances_writer(True)
    except Exception:
        pass

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def nome_file_consigliato(template_id: str, pratica: dict, cliente: dict) -> str:
    """Nome del PDF scaricato, diverso per categoria:
      - preventivo:   '<numero preventivo> - <ASL>'      (es. 'AM0105.26 - RM2')
      - prescrizione: 'Prescrizione - <COGNOME> - <ddmm.aa>'
      - delega:       'Deleghe - <COGNOME> - <ddmm.aa>'
      - altri:        '<numero> - <NOME COMPLETO> - <label>'  (comportamento storico)
    La data è quella di creazione del file (oggi), formato ddmm.aa.
    """
    tpl = PDF_TEMPLATES.get(template_id, {})
    pratica = pratica or {}
    cliente = cliente or {}
    cat = tpl.get("categoria")
    cognome = (cliente.get("cognome") or "").strip().upper() or "CLIENTE"
    oggi = date.today().strftime("%d%m.%y")  # ddmm.aa

    if cat == "preventivo":
        numero = numero_preventivo(pratica, cliente) or f"pratica-{pratica.get('id', '')}"
        asl = _asl(pratica, cliente)
        base = f"{numero} - {asl}".strip(" -")
    elif cat == "prescrizione":
        base = f"Prescrizione - {cognome} - {oggi}"
    elif cat == "delega":
        base = f"Deleghe - {cognome} - {oggi}"
    else:
        numero = numero_preventivo(pratica, cliente) or f"pratica-{pratica.get('id', '')}"
        nome = _nome_completo(cliente).upper() or "CLIENTE"
        base = f"{numero} - {nome} - {tpl.get('label', template_id)}".strip(" -")

    # rimuove caratteri problematici nei filename
    for ch in '/\\:*?"<>|':
        base = base.replace(ch, "-")
    return base + ".pdf"
