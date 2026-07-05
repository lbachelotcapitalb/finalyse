"""Orchestrateur. Point d'entrée unique qui renverra le contrat JSON consommé
plus tard par le front bWealthy et le MCP. Rien d'imprimé ici : que des données.
"""
import numpy as np
from . import universe as U
from . import data as D
from . import optimize as opt
from . import metrics as m
from . import backtest as bt
from . import montecarlo as mc

# Profils client = cible de PERTE MAX historique (max drawdown), le langage du client.
PROFILES = {"prudent": 0.10, "equilibre": 0.20, "dynamique": 0.35}


def _weights_dict(w, keys):
    return {k: round(float(x), 4) for k, x in zip(keys, w) if x > 5e-4}


def _port_returns(returns_df, w, keys):
    wd = dict(zip(keys, w))
    W = np.array([wd.get(c, 0.0) for c in returns_df.columns])
    return returns_df.values @ W


def _bench_returns(returns_df):
    """Benchmark 60/40 si les clés existent, sinon repli équipondéré (univers UC/UCITS)."""
    cols = list(returns_df.columns)
    w = np.array([U.BENCHMARK_6040.get(c, 0.0) for c in cols])
    if w.sum() > 0:
        return returns_df.values @ (w / w.sum()), "60% actions US / 40% souverain 7-10a"
    w = np.ones(len(cols)) / len(cols)
    return returns_df.values @ w, "équipondéré (univers sans clés benchmark)"


def _pick_profile_portfolio(returns_df, frontier, target_maxdd, keys):
    """Sur la frontière drawdown-efficiente, prend le portefeuille de plus fort
    rendement dont le MAX DRAWDOWN composé réalisé (in-sample) <= cible."""
    best = None
    for pt in frontier:
        r = _port_returns(returns_df, pt["weights"], keys)
        mdd = m.max_drawdown(r)
        cg = m.cagr(r)
        if mdd <= target_maxdd and (best is None or cg > best["cagr"]):
            best = {"weights": pt["weights"], "cagr": cg, "maxdd": mdd,
                    "cdar_budget": pt["cdar_budget"]}
    return best


def run(alpha=0.95, wmax=0.35, verbose=True, source="auto"):
    """source: 'eodhd' (prod), 'live' (Yahoo/Stooq), 'synthetic', ou 'auto' (live puis repli synthétique)."""
    if source == "synthetic":
        from . import synth
        ret, meta = synth.generate()
    elif source == "eodhd":
        from . import data_eodhd as DE
        symbols = {k: t.upper() for k, t in U.TICKERS.items()}   # spy.us -> SPY.US
        ret, _px, meta = DE.prepare(symbols, verbose=verbose)
    elif source == "eodhd_deep":
        from . import data_eodhd as DE
        ret, _px, meta = DE.prepare(U.DEEP_HISTORY, start="1999-01-01", verbose=verbose)
    elif source == "eodhd_uc":
        from . import data_eodhd as DE
        ret, _px, meta = DE.prepare(U.UC_SYMBOLS, start="1999-01-01", verbose=verbose)
    elif source == "eodhd_ucits":
        from . import data_eodhd as DE
        if not U.UCITS_SYMBOLS:
            raise RuntimeError("U.UCITS_SYMBOLS vide — lancer scripts/discover_ucits.py d'abord.")
        ret, _px, meta = DE.prepare(U.UCITS_SYMBOLS, start="1999-01-01", verbose=verbose)
    else:
        try:
            ret, _px, meta = D.prepare(U.TICKERS, verbose=verbose)
        except Exception as e:  # noqa: BLE001
            if source == "live":
                raise
            from . import synth
            if verbose:
                print(f"[!] Sources live injoignables ({e}).\n    → repli sur panel SYNTHÉTIQUE (dé-risquage moteur).")
            ret, meta = synth.generate()
    keys = list(ret.columns)
    labels = {**U.LABELS, **U.UC_LABELS}   # résout les clés de tout univers connu
    result = {"meta": meta, "univers": {k: labels.get(k, k) for k in keys},
              "params": {"alpha": alpha, "wmax": wmax}, "portefeuilles": {}, "benchmark": {}}

    # Benchmark (60/40 si dispo, sinon équipondéré)
    rb, bench_def = _bench_returns(ret)
    result["benchmark"] = {"definition": bench_def, "in_sample": m.summary(rb, alpha)}

    # --- Portefeuilles sans forecast de rendement (robustes) ---
    w_mc, _ = opt.min_cdar(ret.values, alpha, wmax)
    w_hrp = opt.hrp(ret.values, wmax=wmax)
    w_mv, shrink = opt.min_variance_lw(ret.values, wmax)

    base = {
        "min_cdar": ("Drawdown minimal (CDaR, sans rendement espéré)", w_mc),
        "hrp": ("HRP — le plus décorrélé (López de Prado)", w_hrp),
        "minvar_lw": ("Min-variance Ledoit-Wolf (repère variance)", w_mv),
    }
    curve_returns = {"Benchmark": rb}
    for key, (desc, w) in base.items():
        r = _port_returns(ret, w, keys)
        result["portefeuilles"][key] = {
            "description": desc, "poids": _weights_dict(w, keys),
            "in_sample": m.summary(r, alpha),
        }
        if key == "min_cdar":
            curve_returns["Min-drawdown"] = r
    result["portefeuilles"]["minvar_lw"]["ledoitwolf_shrinkage"] = round(shrink, 3)

    # --- Frontière drawdown-efficiente + portefeuilles par profil ---
    frontier = opt.drawdown_frontier(ret.values, alpha=alpha, wmax=wmax, n_points=14)
    result["frontiere"] = [
        {"cdar_budget": round(p["cdar_budget"], 4),
         **m.summary(_port_returns(ret, p["weights"], keys), alpha)}
        for p in frontier
    ]
    for pname, target in PROFILES.items():
        pick = _pick_profile_portfolio(ret, frontier, target, keys)
        if pick is None:
            pick = {"weights": w_mc, "cdar_budget": None}
        r = _port_returns(ret, pick["weights"], keys)
        result["portefeuilles"][f"profil_{pname}"] = {
            "description": f"Profil {pname} — perte max cible ≤ {int(target*100)}%",
            "cible_maxdd": target, "poids": _weights_dict(pick["weights"], keys),
            "in_sample": m.summary(r, alpha),
        }
        curve_returns[f"Profil {pname}"] = r

    # --- Walk-forward + contrôle d'honnêteté ---
    result["walk_forward"] = {}
    for method, bgt in [("min_cdar", None), ("hrp", None),
                        ("minvar_lw", None), ("cdar_budget", 0.08)]:
        oos, folds = bt.walk_forward(ret, method, cdar_budget=bgt or 0.10,
                                     alpha=alpha, wmax=wmax)
        entry = {"n_folds": len(folds), "oos": m.summary(oos, alpha) if len(oos) else {}}
        if method in ("min_cdar", "cdar_budget"):
            entry["honnetete"] = bt.honesty_check(folds)
        result["walk_forward"][method] = entry

    # --- Monte-Carlo sur le profil équilibré ---
    pick = _pick_profile_portfolio(ret, frontier, PROFILES["equilibre"], keys) or {"weights": w_mc}
    r_eq = _port_returns(ret, pick["weights"], keys)
    result["monte_carlo_equilibre"] = mc.project(r_eq, horizon_years=10, n_sims=2000)

    # --- Courbes perf/drawdown pour le front (downsamplées ~mensuel) ---
    step = max(1, len(ret) // 320)
    dates = [d.strftime("%Y-%m-%d") for d in ret.index][::step]
    courbes = {}
    for name, r in curve_returns.items():
        eq = np.cumprod(1.0 + np.asarray(r, float))
        peak = np.maximum.accumulate(eq)
        dd = eq / peak - 1.0
        courbes[name] = {"dates": dates,
                         "equity": [round(float(x), 4) for x in eq[::step]],
                         "drawdown": [round(float(x), 4) for x in dd[::step]]}
    result["courbes"] = courbes

    return result
