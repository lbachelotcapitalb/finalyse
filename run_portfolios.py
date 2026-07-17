"""Optim CDaR par enveloppe → 3 portefeuilles cibles (CTO / PEA / AV), EN EUR.

Chaîne complète, LIVE (nécessite EODHD_API_TOKEN dans l'env, injecté via
ask-secret.sh / bw-get — jamais en clair) :
  1. bâtit la map devise par instrument (catalogue EODHD par place, caché) ;
  2. par enveloppe : sélectionne un panel diversifié, fetch + convertit en EUR,
     puis min_cdar (drawdown minimal) + HRP + frontière + profils ;
  3. écrit result_portfolios.json et imprime un récap (dont le nombre d'actifs
     non-EUR convertis — la preuve que la conversion opère sur la vraie data).

Usage :  .venv/bin/python run_portfolios.py [--per-class 4] [--wmax 0.35] [--av-only]
"""
import argparse
import csv
import json
import os
import sys

from finalyse import portfolios as P
from finalyse import currency as C

_HERE = os.path.dirname(__file__)
_LISTS = {
    "CTO": ("data/list_cto_robuste.csv", ["XETRA", "PA", "LSE"]),
    "PEA": ("data/list_pea.csv", ["PA"]),
    "AV": ("data/list_av.csv", ["EUFUND"]),
}


def _read_rows(path):
    with open(os.path.join(_HERE, path), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=4)
    ap.add_argument("--wmax", type=float, default=0.35)
    ap.add_argument("--min-years", type=float, default=None,
                    help="filtre historique min (fenêtre commune plus longue)")
    ap.add_argument("--av-fee", type=float, default=0.008,
                    help="frais annuels du contrat AV (couche enveloppe, défaut 0,8 %/an)")
    ap.add_argument("--av-only", action="store_true")
    ap.add_argument("--out", default="result_portfolios.json")
    args = ap.parse_args()

    if not os.environ.get("EODHD_API_TOKEN", "").strip():
        sys.exit("EODHD_API_TOKEN absent — injecter via ask-secret.sh, puis relancer.")

    # Map devise : toutes les places utiles, EUFUND prioritaire pour l'AV.
    print("→ Catalogue devises (EODHD, caché)…")
    maps = C.build_maps(C.DEFAULT_EXCHANGES)
    print(f"  {len(maps[0])} ISIN, {len(maps[1])} codes résolus.")

    envelopes = ["AV"] if args.av_only else ["CTO", "PEA", "AV"]
    result = {"params": {"per_class": args.per_class, "wmax": args.wmax,
                         "min_years": args.min_years}, "enveloppes": {}}

    for env in envelopes:
        path, _places = _LISTS[env]
        rows = _read_rows(path)
        # Nettoyage d'univers par enveloppe (décisions Léo)
        if env == "CTO":
            before = len(rows)
            dropped = [r["name"] for r in rows if P.is_exotic_commodity(r.get("name", ""))]
            rows = [r for r in rows if not P.is_exotic_commodity(r.get("name", ""))]
            if dropped:
                print(f"  [CTO] {len(dropped)}/{before} ETC mono-matière exclus "
                      f"(or + panier large only) : {', '.join(d[:22] for d in dropped[:8])}"
                      f"{'…' if len(dropped) > 8 else ''}")
        if env == "PEA":
            for r in rows:                       # la liste PEA n'a pas de colonne classe
                r["classe"] = P.pea_classe(r.get("name", ""))
            mon = [r["name"] for r in rows if r["classe"] == "monétaire"]
            rows = [r for r in rows if r["classe"] != "monétaire"]
            print(f"  [PEA] classes déduites du nom ; {len(mon)} monétaire(s) exclus.")
        cand = P.select_candidates(rows, per_class=args.per_class,
                                   min_years=args.min_years)
        print(f"\n=== {env} : {len(cand)}/{len(rows)} candidats ===")
        fee = args.av_fee if env == "AV" else 0.0   # frais d'enveloppe : AV seulement
        ret, kept = P.load_eur_returns(cand, env, maps=maps, annual_fee=fee, verbose=True)
        n_non_eur = sum(1 for i in kept if i["ccy"] != "EUR")
        if fee:
            print(f"  frais contrat AV {fee:.2%}/an déduits (net d'enveloppe).")
        print(f"  {len(kept)} actifs retenus, dont {n_non_eur} non-EUR convertis.")
        res = P.optimize_envelope(ret, wmax=args.wmax)
        res["actifs"] = kept
        res["frais_enveloppe_annuel"] = fee
        res["devises"] = {"non_eur": n_non_eur, "total": len(kept)}
        result["enveloppes"][env] = res
        mc = res["min_cdar"]
        print(f"  min_cdar: cdar95={mc['in_sample']['cdar95']} "
              f"maxdd={mc['in_sample']['max_drawdown']} cagr={mc['in_sample']['cagr']}")

    out = os.path.join(_HERE, args.out)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n✓ {out}")


if __name__ == "__main__":
    main()
