"""
Script una-tantum: porta al 17% la provvigione di tutte le pratiche ancora
attive nel conteggio marginalità (fatturata = FALSE), incluse quelle di
pazienti già inseriti in precedenza — non solo le pratiche create da oggi.

Aggiorna solo le pratiche attualmente alla provvigione standard 16%
(provvigione_pct = 0.16): lascia invariate le pratiche a tariffa ridotta
Nemo (0.12) e quelle già al 17%/18%.

Dry-run di default (mostra solo cosa verrebbe cambiato). Per applicare:

    DATABASE_URL='postgres://…' python3 update_provvigione_17.py --apply

In locale (SQLite, nessun DATABASE_URL) basta:

    python3 update_provvigione_17.py --apply
"""
import sys

from config import PROVVIGIONE_PCT, PROVVIGIONE_PCT_17
from database import get_db, _PH, _FATTURATA_TRUE

APPLY = "--apply" in sys.argv[1:]


def main():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, nome_paziente, data_pratica, provvigione_pct "
            f"FROM pratiche "
            f"WHERE fatturata <> {_FATTURATA_TRUE} "
            f"AND provvigione_pct = {_PH} "
            f"ORDER BY id",
            (PROVVIGIONE_PCT,),
        )
        rows = cur.fetchall()

        if not rows:
            print("Nessuna pratica attiva alla provvigione standard 16%: nulla da fare.")
            return

        print(f"Pratiche attive (non fatturate) a {PROVVIGIONE_PCT*100:.0f}% → {PROVVIGIONE_PCT_17*100:.0f}%:")
        for r in rows:
            print(f"  #{r['id']:<5} {r['nome_paziente']:<30} {r['data_pratica']}")
        print(f"\nTotale: {len(rows)} pratiche.")

        if not APPLY:
            print("\n[DRY-RUN] Nessuna modifica applicata. Rilancia con --apply per confermare.")
            return

        cur.execute(
            f"UPDATE pratiche SET provvigione_pct = {_PH} "
            f"WHERE fatturata <> {_FATTURATA_TRUE} AND provvigione_pct = {_PH}",
            (PROVVIGIONE_PCT_17, PROVVIGIONE_PCT),
        )
        print(f"\n[APPLICATO] {len(rows)} pratiche aggiornate al {PROVVIGIONE_PCT_17*100:.0f}%.")


if __name__ == "__main__":
    main()
