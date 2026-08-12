"""
Rinnovi ausili/ortesi: calcolo delle scadenze e costruzione dell'elenco.

Regole (config.py):
  - la scadenza si calcola dalla DATA PRATICA (solo mese/anno) + i mesi previsti
    per la categoria dell'ausilio;
  - categoria dedotta per parole chiave da tipologia/ausilio (correggibile a mano);
  - minori (< 18 anni alla data pratica) → mesi ridotti.

L'elenco unisce due sorgenti (scelta "Entrambe"):
  - rinnovi inseriti a mano (tabella `rinnovi`);
  - suggerimenti automatici dalle pratiche fatturate non ancora gestite.
Finestra: scadenza entro 6 mesi da oggi, incluse quelle già scadute.
"""
from datetime import date, datetime

from config import (
    RINNOVO_CATEGORIE, RINNOVO_MESI, RINNOVO_MESI_MINORE,
    RINNOVO_MESI_DEFAULT, RINNOVO_KEYWORDS,
)
from database import get_db, _PH, _FATTURATA_TRUE, last_inserted_id

FINESTRA_MESI = 6  # "in scadenza" = scadenza entro N mesi da oggi (+ già scadute)


# ── Date ──────────────────────────────────────────────────────────────────────

def _as_date(v):
    """Converte in date valori che arrivano da DB o form (date/datetime/str)."""
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v)[:10]
    try:
        return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except (ValueError, IndexError):
        return None


def _iso(d):
    return d.isoformat() if isinstance(d, date) else None


def _primo_del_mese(d: date) -> date:
    return date(d.year, d.month, 1)


def _aggiungi_mesi(d: date, mesi: int) -> date:
    """Somma `mesi` a una data considerando solo mese/anno (giorno = 1)."""
    tot = d.year * 12 + (d.month - 1) + int(mesi)
    return date(tot // 12, tot % 12 + 1, 1)


# ── Regole di rinnovo ─────────────────────────────────────────────────────────

def classifica_categoria(*testi) -> str:
    """Deduce la categoria di rinnovo da tipologia/ausilio (parole chiave)."""
    blob = " ".join(str(t) for t in testi if t).lower()
    for categoria, chiavi in RINNOVO_KEYWORDS.items():
        if any(k in blob for k in chiavi):
            return categoria
    return "standard"


def is_minore(data_nascita, data_rif) -> bool:
    """True se alla `data_rif` il paziente ha meno di 18 anni. Nascita ignota → False."""
    dn = _as_date(data_nascita)
    dr = _as_date(data_rif)
    if not dn or not dr:
        return False
    try:
        diciottesimo = date(dn.year + 18, dn.month, dn.day)
    except ValueError:  # 29 febbraio
        diciottesimo = date(dn.year + 18, dn.month, 28)
    return dr < diciottesimo


def mesi_per(categoria: str, minore: bool) -> int:
    tabella = RINNOVO_MESI_MINORE if minore else RINNOVO_MESI
    return tabella.get(categoria, RINNOVO_MESI_DEFAULT)


def categoria_label(categoria: str) -> str:
    return RINNOVO_CATEGORIE.get(categoria, categoria)


def calcola(data_pratica, categoria: str, data_nascita=None, mesi_override=None):
    """Ritorna (mesi, data_rinnovo, minore) per una riga.
    `mesi_override` (se valorizzato) prevale sul calcolo per categoria."""
    dp = _as_date(data_pratica)
    minore = is_minore(data_nascita, dp) if dp else False
    if mesi_override:
        mesi = int(mesi_override)
    else:
        mesi = mesi_per(categoria, minore)
    scad = _aggiungi_mesi(dp, mesi) if dp else None
    return mesi, scad, minore


# ── Elenco (manuali + automatici dalle pratiche) ──────────────────────────────

def _limite_finestra() -> date:
    """Primo giorno del mese limite: scadenze fino a questo mese (incluso)."""
    return _aggiungi_mesi(_primo_del_mese(date.today()), FINESTRA_MESI)


def _decora(riga: dict) -> dict:
    """Aggiunge campi derivati per la vista (scaduto, mesi mancanti, etichette)."""
    scad = _as_date(riga.get("data_rinnovo"))
    oggi_mese = _primo_del_mese(date.today())
    riga["scaduto"] = bool(scad and scad < oggi_mese)
    if scad:
        riga["mesi_mancanti"] = (scad.year - oggi_mese.year) * 12 + (scad.month - oggi_mese.month)
    else:
        riga["mesi_mancanti"] = None
    riga["categoria_label"] = categoria_label(riga.get("categoria") or "standard")
    return riga


def _nome_display(cognome, nome, fallback_cognome="", fallback_nome=""):
    cog = (cognome or fallback_cognome or "").strip()
    nom = (nome or fallback_nome or "").strip()
    return (f"{cog} {nom}").strip() or "—"


def elenco():
    """Elenco unificato dei rinnovi in scadenza (manuali + automatici), ordinato
    per data di scadenza crescente (i più urgenti / scaduti in cima)."""
    limite = _iso(_limite_finestra())
    righe = []
    with get_db() as conn:
        cur = conn.cursor()

        # 1) Rinnovi manuali ancora da rinnovare, entro la finestra
        cur.execute(
            f"""SELECT r.*, c.cognome AS c_cognome, c.nome AS c_nome, c.data_nascita
                FROM rinnovi r
                LEFT JOIN clienti c ON c.id = r.cliente_id
                WHERE r.stato = 'da_rinnovare'
                  AND r.data_rinnovo IS NOT NULL
                  AND r.data_rinnovo <= {_PH}""",
            (limite,),
        )
        for r in cur.fetchall():
            r = dict(r)
            righe.append(_decora({
                "origine": "manuale",
                "id": r["id"],
                "pratica_id": r.get("pratica_origine_id"),
                "cliente_id": r.get("cliente_id"),
                "nominativo": _nome_display(r.get("c_cognome"), r.get("c_nome"),
                                            r.get("cognome"), r.get("nome")),
                "tipologia": r.get("tipologia"),
                "ausilio": r.get("ausilio"),
                "categoria": r.get("categoria") or "standard",
                "data_pratica": _as_date(r.get("data_pratica")),
                "mesi": r.get("mesi_rinnovo"),
                "data_rinnovo": _as_date(r.get("data_rinnovo")),
                "note": r.get("note"),
                "stato": r.get("stato"),
            }))

        # 2) Suggerimenti dalle pratiche fatturate non ancora "gestite" (nessun
        #    rinnovo già collegato a quella pratica)
        cur.execute(
            f"""SELECT p.id AS pratica_id, p.data_pratica, p.tipologia, p.ausilio,
                       p.cliente_id, p.nome_paziente,
                       c.cognome AS c_cognome, c.nome AS c_nome, c.data_nascita
                FROM pratiche p
                LEFT JOIN clienti c ON c.id = p.cliente_id
                WHERE p.fatturata = {_FATTURATA_TRUE}
                  AND p.data_pratica IS NOT NULL
                  AND p.id NOT IN (
                        SELECT pratica_origine_id FROM rinnovi
                        WHERE pratica_origine_id IS NOT NULL)"""
        )
        limite_d = _limite_finestra()
        for p in cur.fetchall():
            p = dict(p)
            categoria = classifica_categoria(p.get("tipologia"), p.get("ausilio"))
            mesi, scad, _minore = calcola(p.get("data_pratica"), categoria, p.get("data_nascita"))
            if not scad or scad > limite_d:
                continue
            if p.get("c_cognome") or p.get("c_nome"):
                nominativo = _nome_display(p.get("c_cognome"), p.get("c_nome"))
            else:
                nominativo = (p.get("nome_paziente") or "").strip() or "—"
            righe.append(_decora({
                "origine": "pratica",
                "id": None,
                "pratica_id": p["pratica_id"],
                "cliente_id": p.get("cliente_id"),
                "nominativo": nominativo,
                "tipologia": p.get("tipologia"),
                "ausilio": p.get("ausilio"),
                "categoria": categoria,
                "data_pratica": _as_date(p.get("data_pratica")),
                "mesi": mesi,
                "data_rinnovo": scad,
                "note": None,
                "stato": "da_rinnovare",
            }))

    righe.sort(key=lambda r: (r["data_rinnovo"] or date.max))
    return righe


# ── Scrittura ─────────────────────────────────────────────────────────────────

def crea(*, cliente_id, nome, cognome, categoria, tipologia, ausilio,
         data_pratica, data_nascita=None, mesi_override=None, note=None,
         pratica_origine_id=None, stato="da_rinnovare", creato_da=None) -> int:
    """Inserisce un rinnovo calcolandone la scadenza. Ritorna l'id."""
    mesi, scad, _minore = calcola(data_pratica, categoria, data_nascita, mesi_override)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""INSERT INTO rinnovi
                (cliente_id, nome, cognome, categoria, tipologia, ausilio,
                 data_pratica, mesi_rinnovo, data_rinnovo, pratica_origine_id,
                 stato, note, creato_da)
                VALUES ({_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH},{_PH})""",
            (cliente_id, (nome or "").strip(), (cognome or "").strip(), categoria,
             tipologia, ausilio, _iso(_as_date(data_pratica)),
             mesi_override or None, _iso(scad), pratica_origine_id, stato,
             note, creato_da),
        )
        return last_inserted_id(cur)


def aggiorna(rinnovo_id, *, categoria, tipologia, ausilio, data_pratica,
             data_nascita=None, mesi_override=None, note=None) -> None:
    mesi, scad, _minore = calcola(data_pratica, categoria, data_nascita, mesi_override)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""UPDATE rinnovi SET categoria = {_PH}, tipologia = {_PH}, ausilio = {_PH},
                    data_pratica = {_PH}, mesi_rinnovo = {_PH}, data_rinnovo = {_PH}, note = {_PH}
                WHERE id = {_PH}""",
            (categoria, tipologia, ausilio, _iso(_as_date(data_pratica)),
             mesi_override or None, _iso(scad), note, rinnovo_id),
        )


def imposta_stato(rinnovo_id, stato) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE rinnovi SET stato = {_PH} WHERE id = {_PH}", (stato, rinnovo_id))


def elimina(rinnovo_id) -> None:
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM rinnovi WHERE id = {_PH}", (rinnovo_id,))


def leggi(rinnovo_id):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT r.*, c.data_nascita
                FROM rinnovi r LEFT JOIN clienti c ON c.id = r.cliente_id
                WHERE r.id = {_PH}""",
            (rinnovo_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def pratica_per_rinnovo(pratica_id):
    """Dati minimi di una pratica fatturata, per materializzare un rinnovo da essa."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""SELECT p.id, p.data_pratica, p.tipologia, p.ausilio, p.cliente_id,
                       p.nome_paziente, c.cognome, c.nome, c.data_nascita
                FROM pratiche p LEFT JOIN clienti c ON c.id = p.cliente_id
                WHERE p.id = {_PH}""",
            (pratica_id,))
        row = cur.fetchone()
        return dict(row) if row else None
