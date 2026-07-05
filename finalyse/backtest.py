"""Validation walk-forward.

Estime les poids sur une fenêtre train, les fige sur la fenêtre test suivante,
roule. Concatène les rendements OUT-OF-SAMPLE et les note. Contrôle d'honnêteté
central : le drawdown réalisé hors-échantillon vs la contrainte imposée
in-sample — c'est là que l'overfitting du drawdown se voit.
"""
import numpy as np
from . import optimize as opt
from . import metrics as m


def _weights_for(method, R_train, cdar_budget, alpha, wmax):
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


def walk_forward(returns, method, train=260, test=52, step=52,
                 cdar_budget=0.10, alpha=0.95, wmax=0.35):
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
        w = _weights_for(method, tr, cdar_budget, alpha, wmax)
        seg = te @ w
        oos.append(seg)
        folds.append({
            "train_start": str(returns.index[start].date()),
            "test_start": str(returns.index[start + train].date()),
            "test_end": str(returns.index[te_end - 1].date()),
            "insample_cdar": round(m.cdar(tr @ w, alpha), 4),
            "oos_maxdd": round(m.max_drawdown(seg), 4) if len(seg) > 3 else None,
        })
        start += step
    oos = np.concatenate(oos) if oos else np.array([])
    return oos, folds


def honesty_check(folds):
    """Compare le CDaR in-sample moyen au max drawdown OOS moyen.
    ratio > 1 => le réalisé dépasse la promesse (drawdown sous-estimé in-sample).
    """
    ins = [f["insample_cdar"] for f in folds if f["insample_cdar"] is not None]
    oos = [f["oos_maxdd"] for f in folds if f["oos_maxdd"] is not None]
    if not ins or not oos:
        return {}
    ins_m, oos_m = float(np.mean(ins)), float(np.mean(oos))
    return {
        "insample_cdar_moy": round(ins_m, 4),
        "oos_maxdd_moy": round(oos_m, 4),
        "ratio_realise_sur_promesse": round(oos_m / ins_m, 2) if ins_m else None,
    }
