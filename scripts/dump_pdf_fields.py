"""
Estrae i nomi dei campi AcroForm da tutti i PDF in assets/pdf-templates/
e li salva in assets/pdf-templates/pdf_fields.json.

Uso:
    python scripts/dump_pdf_fields.py

Serve come base di verità per la mappatura campi in pdf_filler.py:
i documenti scritti a mano (CRM AM/PDF_FIELD_MAP.md) sono risultati obsoleti,
quindi la fonte autorevole sono i PDF reali letti con pypdf.
"""
import glob
import json
import os
import sys

import pypdf

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets", "pdf-templates",
)

# Mappa /FT -> etichetta leggibile
_FT_LABEL = {
    "/Tx": "text",
    "/Btn": "button",
    "/Ch": "choice",
    "/Sig": "signature",
}


def dump_one(path: str) -> dict:
    reader = pypdf.PdfReader(path)
    fields = reader.get_fields() or {}
    campi = []
    for nome, f in fields.items():
        ft = f.get("/FT")
        if ft is None:
            continue  # campo padre/gruppo, non scrivibile
        campi.append({
            "nome": nome,
            "tipo": _FT_LABEL.get(ft, str(ft)),
            "valore_default": f.get("/V") or "",
        })
    campi.sort(key=lambda c: c["nome"])
    return {
        "file": os.path.basename(path),
        "pagine": len(reader.pages),
        "num_campi": len(campi),
        "num_text": sum(1 for c in campi if c["tipo"] == "text"),
        "campi": campi,
    }


def main() -> int:
    pdfs = sorted(glob.glob(os.path.join(TEMPLATES_DIR, "*.pdf")))
    if not pdfs:
        print(f"Nessun PDF trovato in {TEMPLATES_DIR}", file=sys.stderr)
        return 1

    risultato = {os.path.basename(p): dump_one(p) for p in pdfs}

    out = os.path.join(TEMPLATES_DIR, "pdf_fields.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(risultato, fh, ensure_ascii=False, indent=2)

    for nome, info in risultato.items():
        print(f"{info['num_text']:>3} text / {info['num_campi']:>3} campi · {info['pagine']}p · {nome}")
    print(f"\nScritto: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
