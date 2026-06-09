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
        "stato": "parziale",  # sezione anagrafica OK; righe ausili in arrivo (Fase 3)
        "richiede_cliente": True,
    },
}


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

def build_field_map(template_id: str, pratica: dict, cliente: dict) -> dict:
    cliente = cliente or {}
    pratica = pratica or {}
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
        return {
            "preventivo_assistito": _nome_completo(cliente),
            "preventivo_nato_luogo": (cliente.get("luogo_nascita") or "").strip(),
            "preventivo_nato_data": _fmt_data(cliente.get("data_nascita")),
            "preventivo_residente_via": _via_completa(cliente),
            "preventivo_residente_citta": _citta_completa(cliente),
            "preventivo_asl": _asl(pratica, cliente),
            "preventivo_data": _fmt_data(pratica.get("data_pratica")),
            "preventivo_numero": (pratica.get("numero_pratica") or "").strip(),
            "preventivo_ref_struttura": (pratica.get("medico_struttura") or "").strip(),
            # righe ausili e totali: Fase 3 (servono le righe LEA sulla pratica)
        }

    raise ValueError(f"Template sconosciuto: {template_id}")


# ── Generazione PDF ───────────────────────────────────────────────────────────

def compila_pdf(template_id: str, pratica: dict, cliente: dict) -> bytes:
    tpl = PDF_TEMPLATES.get(template_id)
    if not tpl:
        raise ValueError(f"Template sconosciuto: {template_id}")

    path = os.path.join(TEMPLATES_DIR, tpl["file"])
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File template mancante: {path}")

    field_map = build_field_map(template_id, pratica, cliente)
    # Scarta i valori vuoti: non serve riscriverli e si evita di azzerare default
    field_map = {k: v for k, v in field_map.items() if v not in ("", None)}

    reader = PdfReader(path)
    writer = PdfWriter()
    writer.append(reader)

    for page in writer.pages:
        writer.update_page_form_field_values(page, field_map)

    # NeedAppearances: forza i viewer a renderizzare i valori inseriti
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
    numero = (pratica or {}).get("numero_pratica") or f"pratica-{(pratica or {}).get('id', '')}"
    nome = _nome_completo(cliente or {}).upper() or "CLIENTE"
    label = tpl.get("label", template_id)
    base = f"{numero} - {nome} - {label}".strip(" -")
    # rimuove caratteri problematici nei filename
    for ch in '/\\:*?"<>|':
        base = base.replace(ch, "-")
    return base + ".pdf"
