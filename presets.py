"""
Preset di ausili: set completi di righe (codici ISO + descrizione + q.tà + prezzo)
raggruppati per categoria, gestibili dal gestionale (CRUD).

I preset vivono nel DB (tabelle preset_ausili + preset_righe). Al primo avvio,
se la tabella è vuota, vengono importati dal file data/presets_ausili.json (seed).
"""
import json
import os

from database import get_db, _PH, last_inserted_id

_SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "presets_ausili.json")


# ── Seed iniziale ─────────────────────────────────────────────────────────────

def seed_presets() -> int:
    """Importa i preset dal JSON solo se la tabella è vuota. Restituisce quanti ne crea."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM preset_ausili")
        if cur.fetchone()["n"] > 0:
            return 0
        try:
            with open(_SEED_PATH, encoding="utf-8") as f:
                presets = json.load(f)
        except (OSError, json.JSONDecodeError):
            return 0
        creati = 0
        for p in presets:
            cur.execute(
                f"INSERT INTO preset_ausili (label, categoria) VALUES ({_PH}, {_PH})",
                (p.get("label", ""), p.get("categoria", "")),
            )
            pid = last_inserted_id(cur)
            for i, r in enumerate(p.get("righe", [])):
                cur.execute(
                    f"INSERT INTO preset_righe (preset_id, codice_iso, descrizione, qta, prezzo_unitario, ordine) "
                    f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
                    (pid, r.get("codice_iso", ""), r.get("descrizione", ""),
                     r.get("qta", 1), r.get("prezzo_unitario", 0), i),
                )
            creati += 1
        return creati


# ── Lettura ───────────────────────────────────────────────────────────────────

def lista_preset() -> list:
    """Tutti i preset con il numero di righe, ordinati per categoria e label."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT p.*, COUNT(r.id) AS num_righe
               FROM preset_ausili p
               LEFT JOIN preset_righe r ON r.preset_id = p.id
               GROUP BY p.id
               ORDER BY p.categoria, p.label"""
        )
        return [dict(row) for row in cur.fetchall()]


def preset_per_categoria() -> dict:
    """Preset raggruppati per categoria: {categoria: [preset, ...]}."""
    gruppi: dict = {}
    for p in lista_preset():
        gruppi.setdefault(p.get("categoria") or "Altro", []).append(p)
    return dict(sorted(gruppi.items()))


def get_preset(preset_id) -> dict | None:
    """Un preset completo di righe, o None se non esiste."""
    try:
        pid = int(preset_id)
    except (TypeError, ValueError):
        return None
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM preset_ausili WHERE id = {_PH}", (pid,))
        row = cur.fetchone()
        if not row:
            return None
        preset = dict(row)
        cur.execute(
            f"SELECT * FROM preset_righe WHERE preset_id = {_PH} ORDER BY ordine, id",
            (pid,),
        )
        preset["righe"] = [dict(r) for r in cur.fetchall()]
        return preset


# ── Scrittura ─────────────────────────────────────────────────────────────────

def _inserisci_righe(cur, preset_id, righe):
    for i, r in enumerate(righe):
        codice = (r.get("codice_iso") or "").strip()
        descr = (r.get("descrizione") or "").strip()
        if not codice and not descr:
            continue
        cur.execute(
            f"INSERT INTO preset_righe (preset_id, codice_iso, descrizione, qta, prezzo_unitario, ordine) "
            f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
            (preset_id, codice, descr, r.get("qta", 1) or 1, r.get("prezzo_unitario", 0) or 0, i),
        )


def crea_preset(label: str, categoria: str, righe: list) -> int:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO preset_ausili (label, categoria) VALUES ({_PH}, {_PH})",
            (label.strip(), categoria.strip()),
        )
        pid = last_inserted_id(cur)
        _inserisci_righe(cur, pid, righe)
        return pid


def aggiorna_preset(preset_id, label: str, categoria: str, righe: list):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE preset_ausili SET label = {_PH}, categoria = {_PH} WHERE id = {_PH}",
            (label.strip(), categoria.strip(), preset_id),
        )
        cur.execute(f"DELETE FROM preset_righe WHERE preset_id = {_PH}", (preset_id,))
        _inserisci_righe(cur, preset_id, righe)


def elimina_preset(preset_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM preset_righe WHERE preset_id = {_PH}", (preset_id,))
        cur.execute(f"DELETE FROM preset_ausili WHERE id = {_PH}", (preset_id,))


def categorie_note() -> list:
    """Elenco delle categorie esistenti (per il datalist nel form)."""
    return sorted({p.get("categoria") for p in lista_preset() if p.get("categoria")})


# ── Preset di significato terapeutico (sola lettura, da JSON) ──────────────────

_SIGN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "presets_significato.json")

try:
    with open(_SIGN_PATH, encoding="utf-8") as _f:
        _SIGN_PRESETS = json.load(_f)
except (OSError, json.JSONDecodeError):
    _SIGN_PRESETS = []


def significato_per_categoria() -> dict:
    """Preset di significato terapeutico raggruppati per categoria."""
    gruppi: dict = {}
    for p in _SIGN_PRESETS:
        gruppi.setdefault(p.get("categoria") or "Altro", []).append(p)
    return dict(sorted(gruppi.items()))
