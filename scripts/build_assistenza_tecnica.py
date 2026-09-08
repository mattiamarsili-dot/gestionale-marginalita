"""
Crea da zero il template "Verbale Assistenza Tecnica.pdf".

Modulo rapido per un intervento di assistenza tecnica su un ausilio già in uso
al paziente: si scarica dalla pratica, si fa firmare al paziente su tablet/
cellulare e si archivia (senza upload automatico su Drive, a differenza degli
altri moduli). Stessa carta intestata Sapio degli altri moduli "sapio"
(logo + bande + piè di pagina, ritagliati da `Modulo Assegno.pdf`). Campi:

    paziente               (testo, precompilato) — nome e cognome
    indirizzo_domicilio    (testo, precompilato) — da anagrafica, se presente
    nome_centro            (testo, precompilato) — centro riabilitazione, se presente
    check_domicilio/check_centro (testo, "X" su uno dei due) — luogo scelto nel form di conferma
    ausilio                (testo, precompilato) — ausilio oggetto dell'intervento
    data_intervento        (testo, precompilato) — data odierna
    orario_dalle/orario_alle (testo, precompilati) — ora attuale / +2h, calcolate al momento della generazione
    interventi_effettuati  (testo multi-riga, precompilato) — scritto nel form di conferma
    data_firma             (testo, precompilato) — data ripetuta in fondo
    (riga per la firma disegnata: non è un campo, si firma a mano sul PDF)

Tutti i campi sopra si valorizzano PRIMA del download (form di conferma in
app.py) e restano bloccati: l'unica cosa che si fa a mano è la firma.

Uso:
    python scripts/build_assistenza_tecnica.py

Serve pymupdf (solo per questo script di build, non a runtime). I nomi campo
qui definiti sono la fonte per il ramo `assistenza-tecnica` di
build_field_map() in pdf_filler.py. Dopo aver generato il PDF lanciare anche
`python scripts/dump_pdf_fields.py`.
"""
import io
import os

import pymupdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

TPL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "pdf-templates",
)
OUT = os.path.join(TPL_DIR, "Verbale Assistenza Tecnica.pdf")
SAPIO_SRC = os.path.join(TPL_DIR, "Modulo Assegno.pdf")  # da cui prendere carta intestata

W, H = A4  # 595 x 842 pt
MX = 56.0                      # margine orizzontale
CW = W - 2 * MX               # larghezza colonna testo
FONT = "Helvetica"
FONT_B = "Helvetica-Bold"

# Fasce (in pt dall'alto) della carta intestata Sapio nel modulo sorgente.
HEAD_H = 74.0
FOOT_TOP = 756.0

# Ancora fissa (dal basso) della riga data/firma: lascia spazio pieno alla
# sezione "interventi effettuati" sopra, e un margine pulito sopra il footer.
FIRMA_Y = 118.0

_FIELD = dict(borderStyle="underlined", borderWidth=1, forceBorder=True,
              fillColor=colors.white, borderColor=colors.Color(0.45, 0.45, 0.45),
              fontName="Helvetica", fontSize=10)

# Le due caselle "Domicilio"/"Centro" sono campi testo pieni di bordo (non
# quadratini disegnati): build_field_map ci scrive una "X" in una delle due
# in base alla scelta fatta nel form di conferma, prima del download.
_CHECKFIELD = dict(borderStyle="solid", borderWidth=1, forceBorder=True,
                    fillColor=colors.white, borderColor=colors.Color(0.45, 0.45, 0.45),
                    fontName="Helvetica-Bold", fontSize=10)


def _sapio_strips():
    """Ritaglia header e footer della carta intestata Sapio come immagini a 300 DPI."""
    src = pymupdf.open(SAPIO_SRC)[0]
    head = src.get_pixmap(clip=pymupdf.Rect(0, 0, W, HEAD_H), dpi=300)
    foot = src.get_pixmap(clip=pymupdf.Rect(0, FOOT_TOP, W, H), dpi=300)
    return (ImageReader(io.BytesIO(head.tobytes("png"))),
            ImageReader(io.BytesIO(foot.tobytes("png"))),
            H - FOOT_TOP)


def main() -> int:
    head_img, foot_img, foot_h = _sapio_strips()

    c = canvas.Canvas(OUT, pagesize=A4)
    c.setTitle("Verbale di assistenza tecnica")
    form = c.acroForm

    # ── Carta intestata Sapio (header + footer) ────────────────────────────
    c.drawImage(head_img, 0, H - HEAD_H, width=W, height=HEAD_H, mask="auto")
    c.drawImage(foot_img, 0, 0, width=W, height=foot_h, mask="auto")

    y = H - HEAD_H - 28

    # ── Titolo ──────────────────────────────────────────────────────────────
    c.setFont(FONT_B, 15)
    c.drawString(MX, y, "VERBALE DI ASSISTENZA TECNICA")
    y -= 19
    c.setFont(FONT, 10.5)
    c.setFillGray(0.35)
    c.drawString(MX, y, "Intervento di assistenza tecnica su ausilio in uso al paziente")
    c.setFillGray(0)
    y -= 30

    # ── Paziente ────────────────────────────────────────────────────────────
    c.setFont(FONT, 11)
    c.drawString(MX, y, "Paziente")
    y -= 20
    form.textfield(name="paziente", tooltip="Nome e cognome del paziente",
                   x=MX, y=y - 3, width=CW, height=18, **_FIELD)
    y -= 34

    # ── Luogo dell'intervento ───────────────────────────────────────────────
    c.setFont(FONT_B, 11)
    c.drawString(MX, y, "Luogo dell'intervento")
    y -= 22

    box = 13.0
    c.setFont(FONT, 11)
    form.textfield(name="check_domicilio", tooltip="Spuntato se l'intervento è a domicilio",
                   x=MX, y=y - 9, width=box, height=box, **_CHECKFIELD)
    c.drawString(MX + box + 6, y, "Domicilio del paziente:")
    lbl_w = stringWidth("Domicilio del paziente:  ", FONT, 11)
    form.textfield(name="indirizzo_domicilio", tooltip="Indirizzo di residenza (da anagrafica)",
                   x=MX + box + 6 + lbl_w, y=y - 4, width=CW - box - 6 - lbl_w, height=18, **_FIELD)
    y -= 30

    form.textfield(name="check_centro", tooltip="Spuntato se l'intervento è al centro",
                   x=MX, y=y - 9, width=box, height=box, **_CHECKFIELD)
    c.drawString(MX + box + 6, y, "Centro di riabilitazione:")
    lbl_w2 = stringWidth("Centro di riabilitazione:  ", FONT, 11)
    form.textfield(name="nome_centro", tooltip="Centro di riabilitazione",
                   x=MX + box + 6 + lbl_w2, y=y - 4, width=CW - box - 6 - lbl_w2, height=18, **_FIELD)
    y -= 36

    # ── Data e orario dell'assistenza ───────────────────────────────────────
    c.setFont(FONT_B, 11)
    c.drawString(MX, y, "Data e orario dell'assistenza")
    y -= 22
    c.setFont(FONT, 11)
    c.drawString(MX, y, "Data")
    data_lbl_w = stringWidth("Data  ", FONT, 11)
    form.textfield(name="data_intervento", tooltip="Data dell'intervento",
                   x=MX + data_lbl_w, y=y - 4, width=90, height=18, **_FIELD)

    dalle_x = MX + data_lbl_w + 90 + 24
    c.drawString(dalle_x, y, "Dalle")
    dalle_lbl_w = stringWidth("Dalle  ", FONT, 11)
    form.textfield(name="orario_dalle", tooltip="Ora di inizio",
                   x=dalle_x + dalle_lbl_w, y=y - 4, width=55, height=18, **_FIELD)

    alle_x = dalle_x + dalle_lbl_w + 55 + 16
    c.drawString(alle_x, y, "Alle")
    alle_lbl_w = stringWidth("Alle  ", FONT, 11)
    form.textfield(name="orario_alle", tooltip="Ora di fine",
                   x=alle_x + alle_lbl_w, y=y - 4, width=55, height=18, **_FIELD)
    y -= 40

    # ── Ausilio ────────────────────────────────────────────────────────────
    c.setFont(FONT, 11)
    c.drawString(MX, y, "Ausilio")
    y -= 20
    form.textfield(name="ausilio", tooltip="Ausilio oggetto dell'intervento",
                   x=MX, y=y - 3, width=CW, height=18, **_FIELD)
    y -= 34

    # ── Interventi effettuati (riempie lo spazio fino all'ancora firma) ─────
    c.setFont(FONT_B, 11)
    c.drawString(MX, y, "Interventi effettuati sull'ausilio")
    y -= 8
    box_bottom = FIRMA_Y + 46
    box_h = y - box_bottom
    form.textfield(name="interventi_effettuati", tooltip="Descrizione degli interventi effettuati",
                   x=MX, y=box_bottom, width=CW, height=box_h,
                   fieldFlags="multiline", **_FIELD)

    # ── Data e firma ────────────────────────────────────────────────────────
    c.setFont(FONT, 11)
    c.drawString(MX, FIRMA_Y, "Data intervento")
    lbl_w3 = stringWidth("Data intervento  ", FONT, 11)
    form.textfield(name="data_firma", tooltip="Data (ripetuta)",
                   x=MX + lbl_w3, y=FIRMA_Y - 4, width=90, height=18, **_FIELD)

    firma_x = MX + CW - 220
    c.drawString(firma_x, FIRMA_Y, "Firma del paziente")
    c.setLineWidth(0.8)
    c.line(firma_x + stringWidth("Firma del paziente  ", FONT, 11), FIRMA_Y - 2, MX + CW, FIRMA_Y - 2)

    c.showPage()
    c.save()
    print(f"Scritto: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
