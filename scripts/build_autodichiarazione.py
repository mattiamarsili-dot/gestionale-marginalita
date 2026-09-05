"""
Ricostruisce da zero il template `Autodichiarazione Extratariffario.pdf`.

Il PDF fornito in origine aveva i campi AcroForm accavallati alle righe di testo
e una frase che mescolava 1ª e 3ª persona ("dichiaro ... e richiede ..."). Qui
si genera un modulo pulito, A4, con la stessa carta intestata Sapio degli altri
moduli (logo + bande + piè di pagina con le diciture legali, ripresi da
`Modulo Assegno.pdf`) e 5 campi ben distanziati:

    firmatario  (testo)   — "Io sottoscritto/a ___"
    ruolo       (tendina) — "in qualità di ___"  → Me medesimo / Tutore o delegato
    assistito   (testo)   — "dell'assistito/a ___"
    ausilio     (testo)   — ausilio richiesto
    data        (testo)   — "Roma, ___"

Uso:
    python scripts/build_autodichiarazione.py

Serve pymupdf (solo per questo script di build, non a runtime). I nomi campo
qui definiti sono la fonte per il ramo `autodichiarazione-extratariffario` di
build_field_map() in pdf_filler.py. Dopo aver rigenerato il PDF lanciare anche
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
OUT = os.path.join(TPL_DIR, "Autodichiarazione Extratariffario.pdf")
SAPIO_SRC = os.path.join(TPL_DIR, "Modulo Assegno.pdf")  # da cui prendere carta intestata

W, H = A4  # 595 x 842 pt
MX = 56.0                      # margine orizzontale
CW = W - 2 * MX               # larghezza colonna testo
FONT = "Helvetica"
FONT_B = "Helvetica-Bold"

# Fasce (in pt dall'alto) della carta intestata Sapio nel modulo sorgente:
# logo + bande in cima, bande + diciture legali + logo "90°" in fondo.
HEAD_H = 74.0
FOOT_TOP = 756.0

# Stile comune dei campi: fondo bianco (i default reportlab sono azzurrini e
# resterebbero impressi una volta "appiattito" il modulo), solo la riga di base.
_FIELD = dict(borderStyle="underlined", borderWidth=1, forceBorder=True,
              fillColor=colors.white, borderColor=colors.Color(0.45, 0.45, 0.45),
              fontName="Helvetica", fontSize=10)


def _sapio_strips():
    """Ritaglia header e footer della carta intestata Sapio come immagini a 300 DPI."""
    src = pymupdf.open(SAPIO_SRC)[0]
    head = src.get_pixmap(clip=pymupdf.Rect(0, 0, W, HEAD_H), dpi=300)
    foot = src.get_pixmap(clip=pymupdf.Rect(0, FOOT_TOP, W, H), dpi=300)
    return (ImageReader(io.BytesIO(head.tobytes("png"))),
            ImageReader(io.BytesIO(foot.tobytes("png"))),
            H - FOOT_TOP)  # altezza fascia footer in pt


def _wrap(text, font, size, max_w):
    righe, cur = [], ""
    for parola in text.split():
        prova = parola if not cur else f"{cur} {parola}"
        if stringWidth(prova, font, size) <= max_w:
            cur = prova
        else:
            if cur:
                righe.append(cur)
            cur = parola
    if cur:
        righe.append(cur)
    return righe


def main() -> int:
    head_img, foot_img, foot_h = _sapio_strips()

    c = canvas.Canvas(OUT, pagesize=A4)
    c.setTitle("Autodichiarazione fornitura extratariffario")
    form = c.acroForm

    # ── Carta intestata Sapio (header + footer) ────────────────────────────
    c.drawImage(head_img, 0, H - HEAD_H, width=W, height=HEAD_H, mask="auto")
    c.drawImage(foot_img, 0, 0, width=W, height=foot_h, mask="auto")

    y = H - HEAD_H - 28

    # ── Intestazione documento ────────────────────────────────────────────
    c.setFont(FONT_B, 15)
    c.drawString(MX, y, "AUTODICHIARAZIONE")
    y -= 19
    c.setFont(FONT, 10.5)
    c.setFillGray(0.35)
    c.drawString(MX, y, "Fornitura di ausili in regime extratariffario")
    c.setFillGray(0)
    y -= 30

    # ── "Io sottoscritto/a ___" ─────────────────────────────────────────────
    c.setFont(FONT, 11)
    c.drawString(MX, y, "Io sottoscritto/a")
    y -= 20
    form.textfield(name="firmatario", tooltip="Nome di chi firma (assistito, tutore o delegato)",
                   x=MX, y=y - 3, width=CW, height=18, **_FIELD)
    y -= 34

    # ── "in qualità di [tendina]" ──────────────────────────────────────────
    c.setFont(FONT, 11)
    c.drawString(MX, y, "in qualità di")
    lbl_w = stringWidth("in qualità di  ", FONT, 11)
    form.choice(name="ruolo", tooltip="Rapporto con l'assistito",
                value="Me medesimo",
                options=["Me medesimo", "Tutore / Delegato"],
                x=MX + lbl_w, y=y - 5, width=200, height=20, **_FIELD)
    y -= 30

    # ── "dell'assistito/a ___" ─────────────────────────────────────────────
    c.setFont(FONT, 11)
    c.drawString(MX, y, "dell'assistito/a")
    y -= 20
    form.textfield(name="assistito", tooltip="Nome dell'assistito",
                   x=MX, y=y - 3, width=CW, height=18, **_FIELD)
    y -= 36

    # ── Dichiarazione + ausilio ────────────────────────────────────────────
    for riga in _wrap("dichiaro di voler essere seguito/a e fornito/a nella "
                      "richiesta del seguente ausilio:", FONT, 11, CW):
        c.setFont(FONT, 11)
        c.drawString(MX, y, riga)
        y -= 16
    y -= 8
    form.textfield(name="ausilio", tooltip="Ausilio richiesto",
                   x=MX, y=y - 3, width=CW, height=18, **_FIELD)
    y -= 30
    c.setFont(FONT, 11)
    c.drawString(MX, y, "in regime extratariffario dalla ditta SAPIO LIFE S.r.l.")
    y -= 30

    # ── Impegno ────────────────────────────────────────────────────────────
    testo = ("Chiedo di essere avvisato/a dalla ASL qualora venga reperito un "
             "preventivo più basso rispetto a quello della ditta da me scelta. "
             "In tal caso mi impegno a richiedere l'adeguamento del preventivo "
             "al prezzo più basso presentato, oppure a farmi carico della "
             "differenza di costo.")
    for riga in _wrap(testo, FONT, 11, CW):
        c.setFont(FONT, 11)
        c.drawString(MX, y, riga)
        y -= 16
    y -= 20

    c.setFont(FONT, 11)
    c.drawString(MX, y, "In fede.")
    y -= 44

    # ── Luogo, data e firma ────────────────────────────────────────────────
    c.setFont(FONT, 11)
    c.drawString(MX, y, "Roma,")
    roma_w = stringWidth("Roma,  ", FONT, 11)
    form.textfield(name="data", tooltip="Data",
                   x=MX + roma_w, y=y - 4, width=110, height=18, **_FIELD)
    firma_x = MX + CW - 210
    c.drawString(firma_x, y, "Firma")
    c.setLineWidth(0.8)
    c.line(firma_x + stringWidth("Firma  ", FONT, 11), y - 2, MX + CW, y - 2)

    c.showPage()
    c.save()
    print(f"Scritto: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
