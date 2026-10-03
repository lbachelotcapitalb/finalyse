"""Validation walk-forward.

Estime les poids sur une fenêtre train, les fige sur la fenêtre test suivante,
roule. Concatène les rendements OUT-OF-SAMPLE et les note. Contrôle d'honnêteté
central : le drawdown réalisé hors-échantillon vs la contrainte imposée
in-sample — c'est là que l'overfitting du drawdown se voit.

Le contrôle compare des grandeurs de MÊME HORIZON. Un pli de test dure ~1 an ;
le max drawdown d'un an est mécaniquement plus petit que le CDaR mesuré sur
5 ans de train. Comparer les deux (ce que faisait la v1) rendait le test
indulgent par construction. La promesse est donc le max drawdown moyen des
fenêtres glissantes de la longueur du test, mesuré DANS le train.
"""
import numpy as np
from . import optimize as opt
from . import metrics as m


def _weights_for(method, R_train, cdar_budget, alpha, wmax, target_maxdd=None):
    if method == "profil":                              # v1 : point de frontière (μ historique)
        w, _, _ = opt.profile_on_frontier(R_train, target_maxdd, alpha=alpha, wmax=wmax)
        return w
    if method == "profil_mix":                          # v2 : HRP ↔ 1/N, sans μ
        w, _, _, _ = opt.profile_blend(R_train, target_maxdd, marge=cdar_budget, wmax=wmax)
        return w
    if method == "equipondere":                         # témoin 1/N
        return np.full(R_train.shape[1], 1.0 / R_train.shape[1])
    if method == "min_cdar":
        w, _ = opt.min_cdar(R_train, alpha, wmax)
    elif method == "cdar_budget":
        w, _ = opt.max_return_under_cdar(R_train, cdar_budget, alpha=alpha, wmax=wmax)
        if w is None:                                   # budget infaisable sur ce fold
            w, _ = opt.min_cdar(R_train, alpha, wmax)
    elif method == "hrp":
        w = opt.hrp(R_train, wmax=wmax)
    elif method == "minvar_lw":
        w, _ = opt.min_variance_lw(R_train, wmax)
    else:
        raise ValueError(method)
    return w


def rolling_maxdd(r, window):
    """Max drawdown de chaque fenêtre glissante de `window` semaines."""
    r = np.asarray(r, float)
    if len(r) < window or window < 2:
        return np.array([m.max_drawdown(r)]) if len(r) > 1 else np.array([])
    return np.array([m.max_drawdown(r[i:i + window]) for i in range(len(r) - window + 1)])


def walk_forward(returns, method, train=260, test=52, step=52,
                 cdar_budget=0.10, alpha=0.95, wmax=0.35, target_maxdd=None):
    """Renvoie (oos_returns, folds_meta).
    returns : DataFrame (index temps, colonnes actifs).
    """
    R = returns.values
    T = R.shape[0]
    oos = []
    folds = []
    start = 0
    while start + train + 1 <= T:
        tr = R[start:start + train]
        te_end = min(start + train + test, T)
        te = R[start + train:te_end]
        if len(te) == 0:
            break
        w = _weights_for(method, tr, cdar_budget, alpha, wmax, target_maxdd)
        seg = te @ w
        oos.append(seg)
        win = rolling_maxdd(tr @ w, len(te))
        folds.append({
            "train_start": str(returns.index[start].date()),
            "test_start": str(returns.index[start + train].date()),
            "test_end": str(returns.index[te_end - 1].date()),
            "insample_cdar": round(m.cdar(tr @ w, alpha), 4),
            "insample_maxdd_fenetre_moy": round(float(win.mean()), 4) if len(win) else None,
            "insample_maxdd_fenetre_p95": round(float(np.quantile(win, 0.95)), 4) if len(win) else None,
            "oos_maxdd": round(m.max_drawdown(seg), 4) if len(seg) > 3 else None,
        })
        start += step
    oos = np.concatenate(oos) if oos else np.array([])
    return oos, folds


def honesty_check(folds):
    """Promesse vs réalisé, à horizon égal.

    ratio_realise_sur_promesse = max DD hors-échantillon moyen des plis
    ÷ max DD moyen des fenêtres de même durée dans le train. ≈ 1 si honnête,
    > 1 si l'optimiseur a exploité le passé. `taux_depassement_p95` = part des
    plis dont la perte dépasse le 95e centile promis (attendu ≈ 5 %).
    """
    ok = [f for f in folds if f.get("oos_maxdd") is not None
          and f.get("insample_maxdd_fenetre_moy") is not None]
    if not ok:
        return {}
    ins_m = float(np.mean([f["insample_maxdd_fenetre_moy"] for f in ok]))
    oos_m = float(np.mean([f["oos_maxdd"] for f in ok]))
    dep = [f["oos_maxdd"] > f["insample_maxdd_fenetre_p95"] for f in ok]
    cd = [f["insample_cdar"] for f in ok if f.get("insample_cdar") is not None]
    return {
        "methode": "max DD moyen à horizon égal (fenêtres glissantes = durée du pli)",
        "n_plis": len(ok),
        "insample_maxdd_fenetre_moy": round(ins_m, 4),
        "oos_maxdd_moy": round(oos_m, 4),
        "ratio_realise_sur_promesse": round(oos_m / ins_m, 2) if ins_m else None,
        "taux_depassement_p95": round(float(np.mean(dep)), 2),
        # trace de l'ancienne mesure (CDaR 5 ans vs DD 1 an) — pour comparaison
        "ancien_ratio_cdar_train": round(oos_m / float(np.mean(cd)), 2) if cd and np.mean(cd) else None,
    }
