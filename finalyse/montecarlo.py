"""Projection Monte-Carlo par bootstrap stationnaire (Politis-Romano 1994).

Ré-échantillonne la série de rendements du portefeuille par blocs de longueur
géométrique (moyenne L) : préserve le clustering de volatilité et les queues
épaisses, contrairement à un tirage gaussien i.i.d. On sort la distribution du
multiple terminal ET du max drawdown — c'est ce dernier que le client achète.
"""
import numpy as np
from . import metrics as m


def stationary_bootstrap_paths(returns, horizon, n_sims=2000, mean_block=26, seed=7):
    """returns : 1D array de rendements hebdo du portefeuille.
    Renvoie matrice (n_sims, horizon) de rendements simulés.
    """
    r = np.asarray(returns, float)
    T = len(r)
    rng = np.random.default_rng(seed)
    p = 1.0 / mean_block                                # proba de redémarrer un bloc
    out = np.empty((n_sims, horizon))
    for s in range(n_sims):
        idx = np.empty(horizon, dtype=int)
        i = rng.integers(0, T)
        for t in range(horizon):
            idx[t] = i
            if rng.random() < p:
                i = rng.integers(0, T)                  # nouveau bloc
            else:
                i = (i + 1) % T                         # continue le bloc (circulaire)
        out[s] = r[idx]
    return out


def project(returns, horizon_years=10, n_sims=2000, mean_block=26, seed=7):
    horizon = int(round(horizon_years * m.WEEKS))
    paths = stationary_bootstrap_paths(returns, horizon, n_sims, mean_block, seed)
    terminal = np.prod(1.0 + paths, axis=1)             # multiple du capital
    mdd = np.array([m.max_drawdown(p) for p in paths])
    ann = terminal ** (1.0 / horizon_years) - 1.0
    q = lambda a, x: float(np.quantile(a, x))
    return {
        "horizon_ans": horizon_years,
        "n_sims": n_sims,
        "multiple_terminal": {"p5": round(q(terminal, .05), 3),
                              "p50": round(q(terminal, .50), 3),
                              "p95": round(q(terminal, .95), 3)},
        "rendement_annualise": {"p5": round(q(ann, .05), 4),
                                "p50": round(q(ann, .50), 4),
                                "p95": round(q(ann, .95), 4)},
        "max_drawdown": {"p50": round(q(mdd, .50), 4),
                         "p95": round(q(mdd, .95), 4),
                         "p99": round(q(mdd, .99), 4)},
        "proba_perte_capital": round(float(np.mean(terminal < 1.0)), 4),
    }
