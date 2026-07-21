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

# Ordine fisso delle categorie nella sezione preset (le non elencate vanno in coda).
CATEGORIE_ORDINE = [
    "Moveon", "Bascule", "Elettroniche", "Manuali", "Postura su Misura",
    "Propulsori", "Letto", "Sollevatori", "Wc / Wc Basc.", "Montascale",
]


def _cat_ordine(categoria: str) -> int:
    """Indice della categoria nell'ordine fisso; le non elencate finiscono in coda."""
    try:
        return CATEGORIE_ORDINE.index(categoria)
    except ValueError:
        return len(CATEGORIE_ORDINE)


# ── Seed iniziale ─────────────────────────────────────────────────────────────

def seed_presets() -> int:
    """Importa i preset dal JSON solo se la tabella è vuota. Restituisce quanti ne crea.
    L'ordine dei preset nella categoria segue la posizione nel JSON (campo `ordine`
    esplicito o, in mancanza, l'indice)."""
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
        for idx, p in enumerate(presets):
            cur.execute(
                f"INSERT INTO preset_ausili (label, categoria, ordine) VALUES ({_PH}, {_PH}, {_PH})",
                (p.get("label", ""), p.get("categoria", ""), p.get("ordine", idx)),
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


# ── Migrazione struttura (rinomina/riordina categorie + Moveon) ───────────────
# Applica ai DB già popolati (produzione) la nuova organizzazione della sezione:
# rinomina/riordina le categorie, aggiunge la categoria "Moveon" coi 6 tutori,
# rimuove il vecchio set "Ortesi varie". In-place e NON distruttivo sugli altri
# preset. Idempotente: si può eseguire a ogni avvio.

_RINOMINA_CATEGORIE = {
    "Bascule e recliner": "Bascule",
    "Carrozzine elettroniche": "Elettroniche",
    "Carrozzine manuali": "Manuali",
    "Sistemi posturali": "Postura su Misura",
    "Ausili per la mobilità in ambiente": "Montascale",
}
# "Ausili per la cura personale e domiciliari" viene splittato per label.
_SPLIT_CURA = {
    "Letto articolato con accessori": "Letto",
    "Sollevatore mobile + imbracatura": "Sollevatori",
    "Sedia WC / doccia": "Wc / Wc Basc.",
    "Sedia WC Basculante con accessori": "Wc / Wc Basc.",
}
# Ordine dei preset entro la categoria (label nell'ordine voluto).
_ORDINE_PRESET = {
    "Manuali": [
        "Carrozzina Superleggera Pieghevole + posturale",
        "Carrozzina Superleggera Rigida + posturale",
        "Carrozzina Leggera + posturale base",
    ],
}
# Categoria Moveon: sub-preset (tutore) in ordine, con le loro righe (codice, descr, prezzo).
MOVEON_TUTORI = [
    ("Hand", [("06.06.13.012", "Ortesi funzionale Avambraccio - Mano - Dita", 390.0),
              ("06.06.91.106", "Tenditore", 125.0)]),
    ("Spine", [("06.03.18.033", "Busto statico equilibrato", 1050.0),
               ("06.03.91.724", "Presa scapolo omerale: Rigida lunga", 132.6),
               ("06.12.92.639", "Supporto Addominale", 289.0)]),
    ("Hip", [("06.12.15.003", "Ortesi di posizione per anca doccia rigida bilaterale", 620.0),
             ("06.12.91.218", "Tenditore arto inferiore", 87.0)]),
    ("Afo", [("06.12.06.027", "Ortesi dinamica gamba piede a valva alta", 540.0),
             ("06.12.91.218", "Tenditore arto inferiore", 87.0)]),
    ("Shoulder", [("06.06.30.033", "Ortesi di spalla", 0.0),
                  ("06.06.91.106", "Tenditore", 125.0)]),
    ("Knee", [("06.12.09.003", "Ortesi coscia-gamba a ginocchio esteso", 608.20)]),
]

# Set della categoria "Statica": {label del set: righe (codice, descrizione, prezzo)}.
STATICA_SETS = {
    "Stabilizzatore Supino": [
        ("04.48.91.009", "regolazione della prono-supinazione", 120.0),
        ("04.48.91.012", "regolazione intra ed extra rotazione", 105.0),
        ("04.48.91.015", "regolazione della flesso-estensione", 110.0),
        ("04.48.91.018", "regolazione divaricazione", 360.0),
        ("04.48.91.030", "Quattro ruote", 60.0),
        ("04.48.91.036", "regolazione servoassistita con pistone", 247.0),
        ("04.48.91.045", "sostegni per arto superiore (coppia)", 190.0),
        ("04.48.91.048", "divaricatore di tipo stretto o largo", 100.0),
    ],
    "Stabilizzatore Mobile": [
        ("04.48.91.018", "regolazione divaricazione", 360.0),
        ("04.48.91.030", "Quattro ruote", 60.0),
        ("04.48.91.036", "regolazione servoassistita con pistone", 247.0),
        ("04.48.91.045", "sostegni per arto superiore (coppia)", 190.0),
        ("04.48.91.048", "divaricatore di tipo stretto o largo", 100.0),
    ],
    # Accessori posturali — codici/prezzi ripresi dai preset posturali esistenti.
    "Acce. Post.": [
        ("18.09.91.012", "Cinghia Pettorale Imbottita", 135.0),
        ("18.09.91.015", "Cinghia A 45° Sul Bacino", 105.0),
        ("18.09.91.042", "Cinturini Fermapiede (Coppia)", 18.0),
        ("18.09.91.045", "Fermatallone (Coppia) Aggiuntivo Carrozzine", 30.0),
        ("18.09.91.051", "Tavolino Con Incavo", 190.0),
        ("18.09.39.003", "Modulo Posturale Per Il Capo", 360.0),
    ],
}


def migrate_presets_struttura() -> None:
    """Riorganizza i preset esistenti nella nuova struttura. Idempotente."""
    with get_db() as conn:
        cur = conn.cursor()
        # 1) Rinomina categorie (WHERE sul vecchio nome: al secondo giro non matcha)
        for vecchia, nuova in _RINOMINA_CATEGORIE.items():
            cur.execute(f"UPDATE preset_ausili SET categoria = {_PH} WHERE categoria = {_PH}",
                        (nuova, vecchia))
        # 2) Split della categoria "cura personale" per label del preset
        for label, nuova in _SPLIT_CURA.items():
            cur.execute(
                f"UPDATE preset_ausili SET categoria = {_PH} "
                f"WHERE label = {_PH} AND categoria = {_PH}",
                (nuova, label, "Ausili per la cura personale e domiciliari"))
        # 3) Rimuove il vecchio set "Ortesi varie" (i codici ora sono in Moveon)
        cur.execute(f"DELETE FROM preset_ausili WHERE label = {_PH}",
                    ("Ortesi varie (singoli articoli)",))
        # 4) Ordine dei preset entro le categorie che lo richiedono
        for categoria, labels in _ORDINE_PRESET.items():
            for i, label in enumerate(labels):
                cur.execute(
                    f"UPDATE preset_ausili SET ordine = {_PH} "
                    f"WHERE categoria = {_PH} AND label = {_PH}",
                    (i, categoria, label))
        # 5) Crea la categoria Moveon (una sola volta)
        cur.execute(f"SELECT COUNT(*) AS n FROM preset_ausili WHERE categoria = {_PH}", ("Moveon",))
        if cur.fetchone()["n"] == 0:
            for ordine, (tutore, righe) in enumerate(MOVEON_TUTORI):
                cur.execute(
                    f"INSERT INTO preset_ausili (label, categoria, ordine) VALUES ({_PH}, {_PH}, {_PH})",
                    (tutore, "Moveon", ordine))
                pid = last_inserted_id(cur)
                for i, (codice, descr, prezzo) in enumerate(righe):
                    cur.execute(
                        f"INSERT INTO preset_righe (preset_id, codice_iso, descrizione, qta, prezzo_unitario, ordine) "
                        f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
                        (pid, codice, descr, 1, prezzo, i))
        # 6) Set della categoria "Statica" — robusto e auto-correttivo. Il set può
        #    essere già stato creato a mano in produzione con un nome leggermente
        #    diverso (maiuscole/spazi): lo si abbina IGNORANDO maiuscole e spazi,
        #    così lo si riempie davvero invece di crearne un doppione. Per ogni set:
        #    - abbina i preset esistenti col nome equivalente
        #    - tiene quello con più righe, ne uniforma nome/categoria/ordine
        #    - lo riempie se vuoto; elimina eventuali doppioni rimasti vuoti
        #    - se non esiste, lo crea e lo riempie
        def _norm(s):
            return " ".join((s or "").split()).lower()

        cur.execute("SELECT p.id, p.label, COUNT(r.id) AS n "
                    "FROM preset_ausili p LEFT JOIN preset_righe r ON r.preset_id = p.id "
                    "GROUP BY p.id")
        tutti = [dict(row) for row in cur.fetchall()]

        for ordine, (label, righe) in enumerate(STATICA_SETS.items()):
            simili = [p for p in tutti if _norm(p["label"]) == _norm(label)]
            if simili:
                keep = max(simili, key=lambda p: p["n"])          # preferisci il popolato
                sid = keep["id"]
                cur.execute(
                    f"UPDATE preset_ausili SET label = {_PH}, categoria = {_PH}, ordine = {_PH} WHERE id = {_PH}",
                    (label, "Statica", ordine, sid))
                for p in simili:                                   # elimina doppioni vuoti
                    if p["id"] != sid and p["n"] == 0:
                        cur.execute(f"DELETE FROM preset_ausili WHERE id = {_PH}", (p["id"],))
            else:
                cur.execute(
                    f"INSERT INTO preset_ausili (label, categoria, ordine) VALUES ({_PH}, {_PH}, {_PH})",
                    (label, "Statica", ordine))
                sid = last_inserted_id(cur)
            # Merge idempotente: aggiunge i codici definiti MANCANTI (per codice_iso),
            # senza duplicare quelli già presenti né rimuovere eventuali extra.
            cur.execute(f"SELECT codice_iso FROM preset_righe WHERE preset_id = {_PH}", (sid,))
            presenti = {(r["codice_iso"] or "").strip() for r in cur.fetchall()}
            for i, (codice, descr, prezzo) in enumerate(righe):
                if codice not in presenti:
                    cur.execute(
                        f"INSERT INTO preset_righe (preset_id, codice_iso, descrizione, qta, prezzo_unitario, ordine) "
                        f"VALUES ({_PH}, {_PH}, {_PH}, {_PH}, {_PH}, {_PH})",
                        (sid, codice, descr, 1, prezzo, i))


# ── Lettura ───────────────────────────────────────────────────────────────────

def lista_preset() -> list:
    """Tutti i preset con il numero di righe, ordinati per `ordine` poi label
    (l'ordine di categoria lo applica preset_per_categoria)."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """SELECT p.*, COUNT(r.id) AS num_righe
               FROM preset_ausili p
               LEFT JOIN preset_righe r ON r.preset_id = p.id
               GROUP BY p.id
               ORDER BY p.ordine, p.label"""
        )
        return [dict(row) for row in cur.fetchall()]


def preset_per_categoria() -> dict:
    """Preset raggruppati per categoria, con le categorie nell'ordine fisso
    (CATEGORIE_ORDINE) e i preset già ordinati da lista_preset()."""
    gruppi: dict = {}
    for p in lista_preset():
        gruppi.setdefault(p.get("categoria") or "Altro", []).append(p)
    return dict(sorted(gruppi.items(), key=lambda kv: (_cat_ordine(kv[0]), kv[0])))


def preset_per_categoria_con_righe() -> dict:
    """Come preset_per_categoria ma ogni preset include le sue righe complete
    (codice/descrizione/qtà/prezzo): serve alla vista consultazione + copia."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM preset_ausili")
        presets = {row["id"]: dict(row) for row in cur.fetchall()}
        for p in presets.values():
            p["righe"] = []
        cur.execute("SELECT * FROM preset_righe ORDER BY preset_id, ordine, id")
        for r in cur.fetchall():
            if r["preset_id"] in presets:
                presets[r["preset_id"]]["righe"].append(dict(r))
    ordinati = sorted(
        presets.values(),
        key=lambda p: (_cat_ordine(p.get("categoria") or ""), p.get("ordine", 0), p.get("label") or ""),
    )
    gruppi: dict = {}
    for p in ordinati:
        gruppi.setdefault(p.get("categoria") or "Altro", []).append(p)
    return gruppi


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
        # I nuovi set si accodano in fondo alla loro categoria.
        cur.execute(
            f"SELECT COALESCE(MAX(ordine), -1) + 1 AS n FROM preset_ausili WHERE categoria = {_PH}",
            (categoria.strip(),),
        )
        ordine = cur.fetchone()["n"]
        cur.execute(
            f"INSERT INTO preset_ausili (label, categoria, ordine) VALUES ({_PH}, {_PH}, {_PH})",
            (label.strip(), categoria.strip(), ordine),
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
