"""Batch mensuel : un portefeuille optimal PRÉCALCULÉ par contrat d'assurance-vie.

Idée (décision Léo) : plutôt qu'un solveur live par utilisateur, on simule une fois
par mois la grille complète. Un run par contrat produit DÉJÀ toute l'échelle de
risque (frontière + prudent/équilibré/dynamique + recommandé validé OOS) → ~1,4 s
par contrat, soit ~2 min pour 100 contrats. L'app ne fait ensuite que servir le
portefeuille correspondant au contrat de l'utilisateur : zéro calcul en ligne.

Chaîne par contrat :
  menu réel (finalyse.contrat_univers) → screening DU MENU (menu_screen : couverture
  2008, monétaires exclus, score composite dans le menu) → top-N par classe →
  séries EODHD → conversion EUR → frais du contrat → optimize_envelope →
  finalyse.contrat_portfolios.
  (`--intersect` rejoue l'ancien mode « menu ∩ data/list_av.csv » ; abandonné le
  03/10/2026 : 23 des 32 fonds de cette liste sont des fonds de pension
  britanniques, absents de tout contrat français.)

Un contrat SANS menu est ignoré (l'app retombe alors sur l'univers de référence
générique — dégradation honnête, jamais d'invention de fonds éligibles).

Env : EODHD_API_TOKEN + SUPABASE_URL + SUPABASE_SERVICE_KEY (via bw-get/ask-secret).
Usage : .venv/bin/python run_contrats.py [--per-class 4] [--min-fonds 5] [--contrat code]
"""
import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request

from finalyse import portfolios as P
from finalyse import currency as C
from finalyse import menu_screen as MS

HERE = os.path.dirname(__file__)
LIST_AV = os.path.join(HERE, "data", "list_av.csv")


def _sb(method, path, body=None):
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{base}/rest/v1/{path}", data=data, method=method,
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Content-Profile": "finalyse", "Accept-Profile": "finalyse",
                 "Prefer": "return=representation" if method == "GET" else "return=minimal"})
    r = urllib.request.urlopen(req, timeout=90)
    raw = r.read().decode()
    return json.loads(raw) if raw else None


def _screened_av():
    """Univers AV screené : ISIN → ligne (classe, score, years…)."""
    with open(LIST_AV, encoding="utf-8") as f:
        return {r["isin"].strip().upper(): r for r in csv.DictReader(f)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=4)
    ap.add_argument("--min-fonds", type=int, default=5,
                    help="menu ∩ screené en-dessous duquel on n'optimise pas")
    ap.add_argument("--fee", type=float, default=0.008)
    ap.add_argument("--contrat", help="ne traiter qu'un contrat (code)")
    ap.add_argument("--max-start", default="2008-03-31",
                    help="un fonds doit exister avant cette date (crise de 2008 dans la fenêtre)")
    ap.add_argument("--intersect", action="store_true",
                    help="ancien mode : menu ∩ data/list_av.csv au lieu de screener le menu")
    args = ap.parse_args()

    for v in ("EODHD_API_TOKEN", "SUPABASE_URL"):
        if not os.environ.get(v):
            sys.exit(f"{v} absent de l'env.")

    screened = _screened_av() if args.intersect else {}
    from finalyse import data_eodhd as DE
    tok = DE._token()
    _px = {}

    def fetcher(sym):                       # mémoïsé : screening puis chargement
        if sym not in _px:
            _px[sym] = DE.fetch_cached(sym, tok, start="1999-01-01")
        return _px[sym]
    contrats = _sb("GET", "contrats?select=code,nom&actif=is.true&order=code")
    if args.contrat:
        contrats = [c for c in contrats if c["code"] == args.contrat]
    print(f"→ {len(contrats)} contrat(s) actif(s)")

    print("→ Catalogue devises…")
    maps = C.build_maps(["EUFUND"])

    ok = skipped = 0
    for c in contrats:
        code = c["code"]
        menu = _sb("GET", f"contrat_univers?select=isin,label&contrat_code=eq."
                          f"{urllib.parse.quote(code)}") or []
        isins = [m["isin"].strip().upper() for m in menu]
        if not isins:
            print(f"  [skip] {code}: aucun menu connu → l'app servira l'univers générique")
            skipped += 1
            continue

        rejets = []
        if args.intersect:
            rows = [screened[i] for i in isins if i in screened]
        else:
            rows, rejets = MS.screen_menu(menu, fetcher, max_start=args.max_start)
        if len(rows) < args.min_fonds:
            print(f"  [skip] {code}: {len(rows)}/{len(isins)} fonds du menu retenus au "
                  f"screening (< {args.min_fonds}) — l'app reste sur le générique")
            skipped += 1
            continue

        cand = P.select_candidates(rows, per_class=args.per_class)
        try:
            exclus = []
            ret, kept = P.load_eur_returns(cand, "AV", maps=maps, fetcher=fetcher,
                                           annual_fee=args.fee, verbose=False,
                                           max_start=args.max_start, excluded=exclus)
            res = P.optimize_envelope(ret, wmax=0.35)
        except Exception as e:  # noqa: BLE001 — un contrat qui casse ne stoppe pas le batch
            print(f"  [erreur] {code}: {str(e)[:70]}")
            skipped += 1
            continue

        res["actifs"] = kept
        res["frais_enveloppe_annuel"] = args.fee
        res["devises"] = {"non_eur": sum(1 for i in kept if i["ccy"] != "EUR"), "total": len(kept)}
        res["contrat"] = {"code": code, "nom": c["nom"],
                          "menu_total": len(isins), "menu_screene": len(rows),
                          "menu_retenu": len(cand), "rejets_screening": len(rejets)}
        res["exclus_historique_court"] = exclus

        _sb("PATCH", f"contrat_portfolios?contrat_code=eq.{urllib.parse.quote(code)}"
                     f"&is_current=is.true", {"is_current": False})
        _sb("POST", "contrat_portfolios", {"contrat_code": code, "payload": res,
                                           "is_current": True})
        m = res["min_cdar"]["in_sample"]
        print(f"  ✓ {code}: {len(kept)} fonds retenus / {len(isins)} au menu — "
              f"min_cdar cagr={m['cagr']:.1%} maxDD={m['max_drawdown']:.1%} "
              f"(reco: {res['recommande']['methode']})")
        ok += 1

    print(f"\n✓ {ok} contrat(s) calculé(s), {skipped} ignoré(s).")


if __name__ == "__main__":
    main()
