"""
Preset di ausili: set completi di righe (codici ISO + descrizione + q.tà + prezzo)
raggruppati per categoria. Permettono di inserire in blocco tutte le righe di una
configurazione tipica selezionando semplicemente il preset.

Dati in data/presets_ausili.json (versionati). Caricati una volta all'avvio.
"""
import json
import os

_PRESETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "presets_ausili.json")

try:
    with open(_PRESETS_PATH, encoding="utf-8") as _f:
        _PRESETS = json.load(_f)
except (OSError, json.JSONDecodeError):
    _PRESETS = []

# Indice id → preset per lookup O(1)
_BY_ID = {p["id"]: p for p in _PRESETS}


def lista_preset() -> list:
    """Tutti i preset (id, label, categoria, righe)."""
    return _PRESETS


def preset_per_categoria() -> dict:
    """Preset raggruppati per categoria: {categoria: [preset, ...]} ordinati."""
    gruppi: dict = {}
    for p in _PRESETS:
        gruppi.setdefault(p.get("categoria") or "Altro", []).append(p)
    return dict(sorted(gruppi.items()))


def get_preset(preset_id: str) -> dict | None:
    return _BY_ID.get(preset_id)
