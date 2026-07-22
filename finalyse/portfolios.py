"""Optimisation CDaR PAR ENVELOPPE → 3 portefeuilles cibles (CTO / PEA / AV).

Chaîne : sélection de candidats diversifiés dans une liste screenée → fetch des
séries EODHD → résolution devise → conversion EUR (fx.to_eur) → fenêtre commune +
rendements hebdo → `min_cdar` (drawdown minimal, objectif retenu par Léo) avec
HRP en second avis « le plus décorrélé ». Tout est libellé EN EUR : covariance et
CDaR reflètent le risque réel de l'investisseur euro, change compris.

Séparation nette : `load_eur_returns` (I/O + conversion, réseau) vs `optimize_envelope`
(pur, sur une matrice de rendements) — ce dernier est testable hors-réseau.
"""
import re

import numpy as np

from . import optimize as opt
from . import metrics as m
from . import data as D
from . import backtest as bt
from . import fx
from . import currency as C


# Devise par défaut déduite de la place quand le catalogue ne résout pas (à logger).
_EXCHANGE_CCY = {"XETRA": "EUR", "PA": "EUR", "AS": "EUR", "MI": "EUR",
                 "F": "EUR", "LSE": "GBP", "US": "USD", "SW": "CHF", "EUFUND": None}


# ----------------------------------------------------------------------------
# Nettoyage d'univers (décisions Léo : CTO = or + panier large ; PEA reclassé)
# ----------------------------------------------------------------------------
# Un ETC mono-matière (bétail, cuivre, gaz, soja…) est une série idiosyncratique
# et peu liquide que le min-CDaR EXPLOITE (surajustement). On ne garde côté
# matières que l'or et les paniers LARGES diversifiés (CRB, Rogers RICI…).
_GOLD_RE = re.compile(r"\b(gold|bullion|gold\s*bugs)\b", re.I)
_BROAD_COMMO_RE = re.compile(
    r"(crb|rogers|rici|core\s*commodity|corecommodity|diversified\s+commodit|"
    r"broad\s+commodit|all\s+commodit|commodities\s+refinitiv|bloomberg\s+commodit|"
    r"energy\s*&\s*metals|energy\s+and\s+metals)", re.I)
_SINGLE_COMMO_RE = re.compile(
    r"(cattle|livestock|lean\s*hog|\bhogs?\b|coffee|sugar|cocoa|wheat|\bcorn\b|maize|"
    r"\bgrain(s)?\b|soybean|\bsoya?\b|natural\s*gas|gasoline|heating\s*oil|crude|\bwti\b|"
    r"brent|petroleum|nickel|\bzinc\b|\blead\b|alumin|copper|\btin\b|cotton|silver|"
    r"platinum|palladium|\bsofts?\b|agricultur|precious\s*metal|carbon)", re.I)


def is_exotic_commodity(name):
    """True si la ligne est un pari mono-matière/secteur étroit à exclure du CTO.
    L'or et les paniers larges sont conservés (ils ne déclenchent pas l'exclusion)."""
    n = name or ""
    if _GOLD_RE.search(n) or _BROAD_COMMO_RE.search(n):
        return False
    return bool(_SINGLE_COMMO_RE.search(n))


def pea_classe(name):
    """Classe d'actif déduite du nom d'un ETF PEA (la liste n'a pas de colonne
    `classe`). Ordre = du plus spécifique au plus générique. 'monétaire' = à
    exclure (cash, MaxDD≈0 fausse la sélection — pitfall screening n°1)."""
    n = (name or "").lower()
    if re.search(r"court\s*terme|mon[ée]taire|money\s*market|overnight|eonia|ester", n):
        return "monétaire"
    if re.search(r"oblig|bond", n):
        return "oblig"
    if re.search(r"immobil|epra|nareit|\breit", n):
        return "immobilier"
    if re.search(r"emerging|[ée]mergent|inde\b|india|china|chine|latin|turkey|"
                 r"asia|asie|hscei|water|eau\b", n):
        return "actions émergents/thème"
    if re.search(r"japan|topix|nikkei", n):
        return "actions Japon"
    if re.search(r"europe|\beuro\b|emu|stoxx|\bcac\b|\bdax\b", n):
        return "actions Europe"
    if re.search(r"s&p\s*500|nasdaq|dow\s*jones|msci\s*usa|united\s*states|\bus\b", n):
        return "actions US"
    if re.search(r"world|monde|acwi|global", n):
        return "actions monde"
    return "actions/autre"


def eodhd_symbol(row, envelope):
    """Symbole EODHD pour une ligne de liste screenée.
    AV : {ISIN}.EUFUND (comme au screening). CTO/PEA : {CODE}.{EXCHANGE}."""
    if envelope.upper() == "AV":
        return f"{row['isin'].strip().upper()}.EUFUND"
    ex = (row.get("exchange") or "").strip().upper()
    return f"{row['code'].strip().upper()}.{ex}"


def apply_annual_fee(ret, annual_fee):
    """Déduit un frais annuel du contrat des rendements hebdo (pur, testable).

    La VL EODHD est déjà NETTE des frais internes du fonds (frais de gestion
    OPCVM). Ce qu'on retranche ici, c'est la couche SUPPLÉMENTAIRE de l'enveloppe :
    les frais de gestion sur unités de compte du contrat d'assurance-vie
    (~0,6-1 %/an), prélevés en plus par l'assureur. Composé exactement :
    (1+r_net) = (1+r_brut)·(1−frais_hebdo), avec frais_hebdo = (1+f)^(1/52)−1.
    Frais uniformes → décale le net, sans bouleverser l'allocation relative ;
    c'est l'honnêteté « net de frais d'enveloppe » pour comparer AV vs CTO/PEA.
    """
    if not annual_fee:
        return ret
    wk_fee = (1.0 + annual_fee) ** (1.0 / 52.0) - 1.0
    return (1.0 + ret) * (1.0 - wk_fee) - 1.0


def load_eur_returns(rows, envelope, maps=None, fx_provider=None,
                     fetcher=None, annual_fee=0.0, verbose=True):
    """rows: liste de dicts (lignes CSV). Renvoie (ret_df EUR, infos).

    Chaque actif : fetch cours → devise (catalogue, repli place) → EUR → colonne
    indexée par ISIN. Puis fenêtre commune + rendements hebdo, et `annual_fee`
    (frais d'enveloppe, ex. AV) déduit. `fetcher(sym)->Series` et `fx_provider(ccy)
    ->Series` sont injectables (tests hors-réseau). `maps` = (by_isin, by_code) de
    currency.build_maps ; None = tout en devise de la place.
    """
    import pandas as pd

    if fetcher is None:
        from . import data_eodhd as DE
        tok = DE._token()
        fetcher = lambda s: DE._fetch_one(s, tok, start="1999-01-01")  # noqa: E731

    cols, infos = {}, []
    for row in rows:
        isin = (row.get("isin") or "").strip().upper()
        code = (row.get("code") or "").strip().upper()
        ex = (row.get("exchange") or ("EUFUND" if envelope.upper() == "AV" else "")).strip().upper()
        sym = eodhd_symbol(row, envelope)
        try:
            px = fetcher(sym)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  [skip] {sym}: {str(e)[:60]}")
            continue
        if px is None or len(px) < 60:
            if verbose:
                print(f"  [skip] {sym}: série trop courte ({0 if px is None else len(px)} pts)")
            continue
        ccy = None
        if maps is not None:
            ccy = C.resolve(isin=isin, code=code, maps=maps, default=None)
        if not ccy:
            ccy = _EXCHANGE_CCY.get(ex) or "EUR"
        eur = fx.to_eur(px, ccy, fx_provider=fx_provider)
        key = isin or code or sym
        cols[key] = eur
        infos.append({"key": key, "symbol": sym, "isin": isin, "code": code,
                      "name": row.get("name", ""), "classe": row.get("classe", ""),
                      "ccy": ccy, "points": int(len(px))})
        if verbose:
            print(f"  {key:<14} {sym:<22} {ccy:<4} {len(px):>5} pts")
    if not cols:
        raise RuntimeError("Aucune série exploitable pour cette enveloppe.")
    px_df = pd.DataFrame(cols).sort_index()
    pxc = D.common_window(px_df)
    ret = apply_annual_fee(D.to_weekly_returns(pxc), annual_fee)
    info_by_key = {i["key"]: i for i in infos}
    kept = [info_by_key[k] for k in ret.columns if k in info_by_key]
    return ret, kept


def optimize_envelope(ret, alpha=0.95, wmax=0.35, profiles=None):
    """Optim CDaR sur une matrice de rendements EUR (pur, hors-réseau).

    Objectif principal : `min_cdar` (drawdown minimal, sans rendement espéré) —
    le choix de Léo. HRP en second avis décorrélation. Frontière drawdown-efficiente
    + portefeuilles par profil de perte max cible. Renvoie un dict prêt à sérialiser.
    """
    keys = list(ret.columns)
    R = ret.values

    def wd(w):
        return {k: round(float(x), 4) for k, x in zip(keys, w) if x > 5e-4}

    def pr(w):
        W = np.array([dict(zip(keys, w)).get(c, 0.0) for c in keys])
        return R @ W

    w_cdar, cdar_val = opt.min_cdar(R, alpha, wmax)
    w_hrp = opt.hrp(R, wmax=wmax)
    out = {
        "n_actifs": len(keys),
        "fenetre": {"start": str(ret.index.min().date()),
                    "end": str(ret.index.max().date()),
                    "semaines": int(len(ret)),
                    "annees": round((ret.index.max() - ret.index.min()).days / 365.25, 1)},
        "params": {"alpha": alpha, "wmax": wmax},
        "min_cdar": {"objectif": "drawdown minimal (CDaR), sans rendement espéré",
                     "cdar_lp": round(float(cdar_val), 4),
                     "poids": wd(w_cdar), "in_sample": m.summary(pr(w_cdar), alpha)},
        "hrp": {"objectif": "le plus décorrélé (López de Prado)",
                "poids": wd(w_hrp), "in_sample": m.summary(pr(w_hrp), alpha)},
    }
    # Frontière + profils de perte max cible
    frontier = opt.drawdown_frontier(R, alpha=alpha, wmax=wmax, n_points=14)
    out["frontiere"] = [{"cdar_budget": round(p["cdar_budget"], 4),
                         **m.summary(pr(p["weights"]), alpha)} for p in frontier]
    prof = profiles or {"prudent": 0.10, "equilibre": 0.20, "dynamique": 0.35}
    out["profils"] = {}
    for name, target in prof.items():
        best = None
        for p in frontier:
            r = pr(p["weights"])
            mdd, cg = m.max_drawdown(r), m.cagr(r)
            if mdd <= target and (best is None or cg > best["_cg"]):
                best = {"weights": p["weights"], "_cg": cg}
        w = best["weights"] if best else w_cdar
        out["profils"][name] = {"cible_maxdd": target, "poids": wd(w),
                                "in_sample": m.summary(pr(w), alpha)}

    # --- Walk-forward OOS : le garde-fou anti-surajustement -------------------
    # On ré-estime les poids sur une fenêtre train, on les fige sur le test
    # suivant, on roule. Un min-CDaR qui exploite une série lisse in-sample voit
    # son drawdown RÉALISÉ hors-échantillon exploser : c'est là qu'on le démasque.
    T = len(ret)
    train = min(260, max(104, T // 2))
    test = 52 if T > 220 else max(20, T // 6)
    oos_block, ratios = {}, {}
    for method in ("min_cdar", "hrp"):
        oos, folds = bt.walk_forward(ret, method, train=train, test=test, step=test,
                                     alpha=alpha, wmax=wmax)
        entry = {"n_folds": len(folds),
                 "oos": m.summary(oos, alpha) if len(oos) > 3 else {}}
        if method == "min_cdar":
            entry["honnetete"] = bt.honesty_check(folds)
            ratios[method] = (entry["honnetete"] or {}).get("ratio_realise_sur_promesse")
        oos_block[method] = entry
    out["walk_forward"] = {"train": train, "test": test, **oos_block}

    # Recommandation : min_cdar seulement s'il tient OOS (ratio réalisé/promesse
    # ≤ 1,4 ET meilleur Calmar OOS que HRP) ; sinon HRP (robuste au bruit).
    def _oos_calmar(meth):
        return (oos_block.get(meth, {}).get("oos") or {}).get("calmar")
    c_cdar, c_hrp = _oos_calmar("min_cdar"), _oos_calmar("hrp")
    ratio = ratios.get("min_cdar")
    ratio_ok = ratio is None or ratio <= 1.4
    calmar_ok = c_cdar is not None and (c_hrp is None or c_cdar >= c_hrp)
    cdar_tient = ratio_ok and calmar_ok
    if cdar_tient:
        motif = "min_cdar tient hors-échantillon (drawdown réalisé ≈ promesse, Calmar OOS ≥ HRP)"
    elif not ratio_ok:
        motif = (f"min_cdar surajuste : drawdown réalisé/promesse={ratio} (>1,4) "
                 f"→ repli HRP décorrélé")
    else:
        motif = (f"min_cdar moins robuste OOS (Calmar {c_cdar} < HRP {c_hrp}) "
                 f"→ repli HRP décorrélé")
    reco = "min_cdar" if cdar_tient else "hrp"
    out["recommande"] = {"methode": reco, "motif": motif,
                         "poids": out[reco]["poids"]}
    return out


def select_candidates(rows, per_class=4, score_key="score", min_years=None):
    """Sélection diversifiée : top `per_class` par classe d'actif (score décroissant).
    `min_years` filtre l'historique court (fenêtre commune plus longue = CDaR plus
    fiable sur les crises). Réduit l'univers screené à un panel décorrélable.
    """
    def fnum(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    pool = rows
    if min_years:
        pool = [r for r in pool if fnum(r.get("years")) >= min_years]
    by_class = {}
    for r in pool:
        by_class.setdefault(r.get("classe", "?"), []).append(r)
    picked = []
    for cls, items in by_class.items():
        items.sort(key=lambda r: fnum(r.get(score_key, r.get("S", 0))), reverse=True)
        picked.extend(items[:per_class])
    return picked
