"""Reconstitue `data/list_*.csv` depuis un résultat de run déjà produit.

POURQUOI CE SCRIPT EXISTE (23/08/2026). Le dossier `data/` est gitignoré — les
séries Quantalys sont sous licence et n'ont jamais eu à être publiées. Le jour où
la copie locale a disparu, les TROIS listes screenées ont disparu avec elle :
`list_cto_robuste.csv` (201 ETF), `list_pea.csv` (21), `list_av.csv` (150 UC). Ni
le VPS ni GitHub n'en portaient de copie. Sans elles, `run_portfolios.py` et
`run_contrats.py` ne démarrent même pas : le moteur ne savait plus que rafraîchir
les cours de ce qu'il connaissait déjà.

CE QUI A SURVÉCU, et que personne n'avait vu comme une sauvegarde : le résultat du
dernier run. Il porte, par enveloppe, un bloc `actifs[]` qui est le MIROIR EXACT
des lignes lues au run — `load_eur_returns` construit ses `infos` avec les mêmes
champs que le CSV d'entrée (key, symbol, isin, code, name, classe, ccy). Deux
copies en vivent : `finalyse.portfolios` en base, et le repli embarqué du front
bwealthy (`src/data/portfolios.json`), lui VERSIONNÉ dans git.

CE QUE CE SCRIPT RESTAURE, ET CE QU'IL NE RESTAURE PAS. Il rend les actifs
RETENUS au dernier run (36 · 12 · 32), pas l'univers SCREENÉ (201 · 21 · 150).
Rejouer `run_portfolios.py` dessus redonne donc le même panel avec des cours à
jour — utile, honnête, et borné : le screening ne peut plus faire remonter un
fonds qui n'avait pas déjà été retenu. Reconstituer le vrai univers demande de
rejouer le screening (méthode en `docs/MODELE.md` § C.8).

Le `score` écrit vaut 1 pour toutes les lignes : elles étaient déjà les meilleures
de leur classe, donc `select_candidates` n'a plus rien à départager. `years` est
dérivé de `points` pour que `--min-years` reste utilisable.

Usage :
  python rebuild_lists.py --from-json ../bwealthy/src/data/portfolios.json
  python rebuild_lists.py --from-supabase        # SUPABASE_URL + SUPABASE_SERVICE_KEY
  python rebuild_lists.py --from-json … --dry-run
"""
import argparse
import csv
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# Nom de fichier par enveloppe : ceux que run_portfolios.py attend, à la lettre.
FILES = {
    "CTO": "list_cto_robuste.csv",
    "PEA": "list_pea.csv",
    "AV": "list_av.csv",
}
COLS = ["code", "isin", "name", "classe", "exchange", "ccy", "points", "years", "score"]

# Un jour de bourse ≈ 1/252 d'année ; une VL hebdo ≈ 1/52. On ne sait pas laquelle
# des deux a produit `points`, donc on prend la convention QUOTIDIENNE (la plus
# fréquente chez EODHD) et on l'assume : `years` ne sert qu'au filtre optionnel.
POINTS_PAR_AN = 252.0


def _from_supabase():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not base or not key:
        sys.exit("SUPABASE_URL et SUPABASE_SERVICE_KEY requis pour --from-supabase.")
    req = urllib.request.Request(
        f"{base}/rest/v1/portfolios?select=payload&is_current=eq.true",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Accept-Profile": "finalyse"})
    with urllib.request.urlopen(req, timeout=30) as r:
        rows = json.load(r)
    if not rows:
        sys.exit("Aucun portefeuille courant dans finalyse.portfolios.")
    return rows[0]["payload"]


def _exchange(actif, env):
    """La place, redéduite du symbole complet (« LU0151325312.EUFUND » → EUFUND)."""
    sym = (actif.get("symbol") or "").strip().upper()
    if "." in sym:
        return sym.rsplit(".", 1)[1]
    return "EUFUND" if env == "AV" else ""


def _rows(payload, env):
    env_block = (payload.get("enveloppes") or {}).get(env) or {}
    out = []
    for a in env_block.get("actifs") or []:
        points = int(a.get("points") or 0)
        out.append({
            "code": (a.get("code") or a.get("key") or "").strip().upper(),
            "isin": (a.get("isin") or "").strip().upper(),
            "name": a.get("name") or "",
            # La liste PEA d'origine n'avait pas de colonne `classe` (run_portfolios
            # la déduit du nom). On l'écrit quand même : une donnée mesurée vaut
            # mieux qu'une déduction, et la déduction reste inoffensive si elle
            # repasse dessus.
            "classe": a.get("classe") or "",
            "exchange": _exchange(a, env),
            "ccy": a.get("ccy") or "",
            "points": points,
            "years": round(points / POINTS_PAR_AN, 2) if points else "",
            "score": 1,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-json", help="result_portfolios.json, ou le repli embarqué du front")
    ap.add_argument("--from-supabase", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="montre le décompte, n'écrit rien")
    args = ap.parse_args()

    if args.from_supabase:
        payload = _from_supabase()
        source = "finalyse.portfolios (Supabase)"
    elif args.from_json:
        with open(args.from_json, encoding="utf-8") as f:
            payload = json.load(f)
        source = args.from_json
    else:
        sys.exit("Donne --from-json <fichier> ou --from-supabase.")

    print(f"source : {source}")
    if not args.dry_run:
        os.makedirs(DATA, exist_ok=True)

    total = 0
    for env, fname in FILES.items():
        rows = _rows(payload, env)
        if not rows:
            print(f"  [{env}] aucun actif dans le payload — liste NON écrite.")
            continue
        classes = {}
        for r in rows:
            classes[r["classe"] or "?"] = classes.get(r["classe"] or "?", 0) + 1
        detail = ", ".join(f"{k} {v}" for k, v in sorted(classes.items()))
        path = os.path.join(DATA, fname)
        if args.dry_run:
            print(f"  [{env}] {len(rows)} lignes → {fname} (non écrit) · {detail}")
        else:
            with open(path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=COLS)
                w.writeheader()
                w.writerows(rows)
            print(f"  [{env}] {len(rows)} lignes → data/{fname} · {detail}")
        total += len(rows)

    print(f"\n{total} lignes au total.")
    print("Rappel : univers RETENU au dernier run, pas l'univers screené. "
          "Le screening complet reste à rejouer (docs/MODELE.md § C.8).")


if __name__ == "__main__":
    main()
