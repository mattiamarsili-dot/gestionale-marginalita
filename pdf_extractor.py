"""
Estrazione del totale netto IVA da PDF di preventivi italiani.

Strategia a due stadi:
  1. Table extraction (pdfplumber) — preciso su PDF con tabelle strutturate
  2. Bottom-up text scan — dall'ultima pagina verso la prima (i totali sono in fondo)

Se entrambi falliscono, ritorna candidati vuoti e suggerito=None.
"""

import re
import os
from typing import Optional

try:
    import pdfplumber
    _PDF_AVAILABLE = True
except ImportError:
    _PDF_AVAILABLE = False


# ── Keyword patterns ──────────────────────────────────────────────────────────

# Priorità 3: keyword che indicano certamente il netto IVA
_KW_ALTO = re.compile(
    r"(totale\s*imponibile|totale\s*netto|imponibile\s*totale|"
    r"netto\s*a\s*pagare|tot\.?\s*imponibile|subtotal|sub\s*total|"
    r"imponibile\b)",
    re.IGNORECASE,
)

# Priorità 2: "Totale" generico, ma non "Totale IVA"
_KW_MEDIO = re.compile(
    r"\b(totale|tot\.?)\b(?!\s*i\.?v\.?a\.?)",
    re.IGNORECASE,
)

# Righe da escludere: contengono IVA come voce separata
_KW_ESCLUDI = re.compile(
    r"\b(i\.?v\.?a\.?|ivato|lordo|inclus[ao]\s+iva|con\s+iva|aliquota)\b",
    re.IGNORECASE,
)

# Pattern importo: gestisce 1.234,56 / 1234,56 / 1,234.56 / 1234.56
_NUM = re.compile(
    r"\b\d{1,3}(?:[.,]\d{3})*[.,]\d{2}\b"   # con decimali
    r"|\b\d+[.,]\d{2}\b"                      # semplice con 2 decimali
    r"|\b\d{3,}\b",                            # intero ≥ 3 cifre (es. 1180)
)


# ── Normalizzazione importo ───────────────────────────────────────────────────

def _normalizza_importo(s: str) -> Optional[float]:
    """
    Converte una stringa con formato italiano/inglese in float.
    Es: "1.234,56" → 1234.56 | "1,234.56" → 1234.56 | "1234" → 1234.0
    """
    s = re.sub(r"[^\d.,]", "", (s or "").strip())
    if not s:
        return None

    virgole = s.count(",")
    punti   = s.count(".")

    if virgole == 1 and punti == 0:
        # "1234,56" oppure "1,234" (migliaia inglese senza decimali)
        parti = s.split(",")
        if len(parti[1]) == 3:
            # migliaia senza decimali es "1,234"
            s = s.replace(",", "")
        else:
            # decimale italiano es "1234,56"
            s = s.replace(",", ".")

    elif virgole == 1 and punti >= 1:
        # "1.234,56" → formato italiano standard
        s = s.replace(".", "").replace(",", ".")

    elif virgole == 0 and punti == 1:
        # "1234.56" oppure "1.234" (migliaia senza decimali)
        parti = s.split(".")
        if len(parti[1]) == 3:
            s = s.replace(".", "")   # migliaia "1.234"
        # altrimenti decimale inglese "1234.56" → lascia com'è

    elif virgole == 0 and punti > 1:
        # "1.234.567" → solo migliaia
        s = s.replace(".", "")

    elif virgole > 1:
        # "1,234,567" → solo migliaia anglosassoni
        s = s.replace(",", "")

    try:
        val = float(s)
        return val if val >= 1 else None
    except ValueError:
        return None


# ── Strategia 1: estrazione da tabelle ───────────────────────────────────────

def _estrai_via_tabelle(pdf) -> list[dict]:
    candidati = []
    for page in pdf.pages:
        try:
            tables = page.extract_tables()
        except Exception:
            continue
        for table in (tables or []):
            for row in table:
                if not row:
                    continue
                # Cerca una cella con keyword
                label_cella = None
                priorita = 0
                for cell in row:
                    testo = (cell or "").strip()
                    if _KW_ESCLUDI.search(testo):
                        break
                    if _KW_ALTO.search(testo):
                        label_cella = testo
                        priorita = 3
                        break
                    if _KW_MEDIO.search(testo) and not priorita:
                        label_cella = testo
                        priorita = 2
                else:
                    if not label_cella:
                        continue
                    # Cerca il numero nelle altre celle (preferibilmente le ultime)
                    for cell in reversed(row):
                        val = _normalizza_importo(cell or "")
                        if val and val >= 1:
                            candidati.append({
                                "label":    label_cella[:80],
                                "importo":  val,
                                "priorita": priorita,
                                "fonte":    "tabella",
                            })
                            break
    return candidati


# ── Strategia 2: bottom-up text scan ─────────────────────────────────────────

def _estrai_via_testo_bottom_up(pdf) -> list[dict]:
    """Scansiona le righe dall'ultima pagina verso la prima (i totali sono in fondo)."""
    righe: list[str] = []
    for page in reversed(pdf.pages):
        testo = page.extract_text() or ""
        righe.extend(reversed(testo.splitlines()))

    candidati = []
    for i, riga in enumerate(righe):
        riga_s = riga.strip()
        if not riga_s:
            continue
        if _KW_ESCLUDI.search(riga_s):
            continue

        priorita = 0
        if _KW_ALTO.search(riga_s):
            priorita = 3
        elif _KW_MEDIO.search(riga_s):
            priorita = 2

        if not priorita:
            continue

        # Cerca numeri nella stessa riga
        numeri = _NUM.findall(riga_s)
        val = None
        for n in reversed(numeri):
            val = _normalizza_importo(n)
            if val and val >= 1:
                break

        # Se la riga ha solo la keyword, guarda la riga "sotto" (i-1 nel buffer bottom-up)
        if val is None and i > 0:
            riga_sotto = righe[i - 1].strip()
            numeri_sotto = _NUM.findall(riga_sotto)
            for n in numeri_sotto:
                val = _normalizza_importo(n)
                if val and val >= 1:
                    break

        if val:
            candidati.append({
                "label":    riga_s[:80],
                "importo":  val,
                "priorita": priorita,
                "fonte":    "testo",
            })

    return candidati


# ── Funzione pubblica ─────────────────────────────────────────────────────────

def estrai_totale_pdf(filepath: str) -> dict:
    """
    Estrae candidati per il totale netto IVA da un PDF.

    Ritorna:
        {
          "candidati": [{"label": ..., "importo": ..., "priorita": ..., "fonte": ...}, ...],
          "suggerito": float | None,
          "errore": str | None,
        }
    """
    if not _PDF_AVAILABLE:
        return {"candidati": [], "suggerito": None, "errore": "pdfplumber non installato"}

    try:
        with pdfplumber.open(filepath) as pdf:
            candidati = _estrai_via_tabelle(pdf) + _estrai_via_testo_bottom_up(pdf)
    except Exception as e:
        return {"candidati": [], "suggerito": None, "errore": str(e)}

    # Deduplicazione: per ogni importo arrotondato a 2 decimali, tieni la priorità più alta
    # e preferisci fonte "tabella" a parità di priorità
    visti: dict[float, dict] = {}
    for c in candidati:
        key = round(c["importo"], 2)
        existing = visti.get(key)
        if not existing:
            visti[key] = c
        elif c["priorita"] > existing["priorita"]:
            visti[key] = c
        elif c["priorita"] == existing["priorita"] and c["fonte"] == "tabella":
            visti[key] = c

    # Ordina: priorità discendente, poi fonte (tabella > testo), poi importo discendente
    fonte_ord = {"tabella": 0, "testo": 1}
    ordinati = sorted(
        visti.values(),
        key=lambda x: (-x["priorita"], fonte_ord.get(x["fonte"], 2), -x["importo"]),
    )
    candidati_unici = ordinati[:5]

    suggerito = candidati_unici[0]["importo"] if candidati_unici else None

    # Pulizia file in produzione (filesystem Render è effimero)
    if os.environ.get("RENDER") or os.environ.get("RAILWAY_ENVIRONMENT"):
        try:
            os.remove(filepath)
        except OSError:
            pass

    return {"candidati": candidati_unici, "suggerito": suggerito, "errore": None}
