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


# ── Catalogo significato terapeutico editabile (DB) ───────────────────────────
# Elenco fisso di articoli, nell'ordine richiesto. Ogni articolo ha una o più
# "motivazioni" (testi) modificabili e salvabili nel catalogo globale.

SIGNIFICATO_ARTICOLI = [
    "MoveOn", "Letto", "Materasso", "Sollevatore",
    "Sedia WC e WC Basculante", "Montascale a cingoli",
    "Carrozzina elettronica", "Carrozzina manuale", "Propulsori",
]

# Testo di default per ogni articolo (correggibile dall'interfaccia).
_SIGN_DEFAULT = {
    "MoveOn": "L'ortesi dinamica MoveOn è indicata per il recupero e il mantenimento funzionale dell'arto, "
              "favorendo il corretto allineamento articolare e contrastando l'instaurarsi di retrazioni e atteggiamenti viziati.",
    "Letto": "Il letto articolato è indicato per garantire posture sicure e variabili durante l'allettamento, "
             "facilitare le manovre assistenziali e prevenire le complicanze legate all'immobilità prolungata.",
    "Materasso": "Il materasso antidecubito è indicato per la prevenzione e il trattamento delle lesioni da pressione "
                 "nel paziente con ridotta mobilità e prolungata permanenza a letto.",
    "Sollevatore": "Il sollevatore è indicato per consentire i trasferimenti in sicurezza del paziente non collaborante "
                   "o con grave deficit motorio, tutelando paziente e caregiver.",
    "Sedia WC e WC Basculante": "La sedia WC/comoda basculante è indicata per garantire l'igiene personale e l'uso dei servizi "
                                "in sicurezza al paziente con grave limitazione della deambulazione e del controllo posturale.",
    "Montascale a cingoli": "Il montascale a cingoli è indicato per il superamento delle barriere architettoniche, "
                            "consentendo al paziente in carrozzina gli spostamenti in sicurezza.",
    "Carrozzina elettronica": "La carrozzina elettronica è indicata per garantire una mobilità autonoma al paziente "
                              "impossibilitato alla deambulazione e all'autospinta efficace, in relazione al grave deficit funzionale.",
    "Carrozzina manuale": "Il presidio è indicato in relazione alla grave limitazione della deambulazione autonoma; "
                          "la carrozzina manuale garantisce gli spostamenti e la partecipazione alle attività quotidiane.",
    "Propulsori": "Il propulsore/servoassistenza è indicato per ridurre il sovraccarico degli arti superiori nell'autospinta, "
                  "ampliando l'autonomia negli spostamenti e tutelando le articolazioni.",
}


def seed_significato_catalogo() -> int:
    """Popola il catalogo significato coi 9 articoli di default se la tabella è vuota."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM significato_catalogo")
        if cur.fetchone()["n"] > 0:
            return 0
        creati = 0
        for ordine, articolo in enumerate(SIGNIFICATO_ARTICOLI):
            cur.execute(
                f"INSERT INTO significato_catalogo (articolo, testo, ordine) VALUES ({_PH}, {_PH}, {_PH})",
                (articolo, _SIGN_DEFAULT.get(articolo, ""), ordine),
            )
            creati += 1
        return creati


def significato_catalogo() -> dict:
    """Catalogo raggruppato per articolo, nell'ordine fisso: {articolo: [{id, testo}, ...]}."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, articolo, testo FROM significato_catalogo ORDER BY articolo, id")
        righe = [dict(r) for r in cur.fetchall()]
    gruppi: dict = {a: [] for a in SIGNIFICATO_ARTICOLI}
    for r in righe:
        gruppi.setdefault(r["articolo"], []).append({"id": r["id"], "testo": r["testo"]})
    # mantiene l'ordine fisso degli articoli, scartando eventuali vuoti non noti
    return {a: gruppi.get(a, []) for a in SIGNIFICATO_ARTICOLI if a in gruppi}


def aggiungi_motivazione(articolo: str, testo: str) -> int:
    """Aggiunge una motivazione al catalogo per l'articolo dato. Restituisce l'id."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO significato_catalogo (articolo, testo, ordine) VALUES ({_PH}, {_PH}, 0)",
            (articolo.strip(), testo.strip()),
        )
        return last_inserted_id(cur)


def aggiorna_motivazione(mot_id: int, testo: str) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE significato_catalogo SET testo = {_PH} WHERE id = {_PH}",
            (testo.strip(), mot_id),
        )


def elimina_motivazione(mot_id: int) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM significato_catalogo WHERE id = {_PH}", (mot_id,))
