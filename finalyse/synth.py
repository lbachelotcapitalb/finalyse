"""Panel synthétique multi-classes à structure de crise réaliste.

Sert UNIQUEMENT à dé-risquer la plomberie du moteur quand les sources live
(Yahoo/Stooq/FRED) sont injoignables (ex. IP de CI/sandbox filtrée). Ce n'est
PAS de la donnée de marché : aucune conclusion d'allocation ne doit en sortir.

Modèle : un facteur de risque commun à vol variable (clustering + 2 krachs),
des bêtas par classe (actions > 0, souverain/or < 0 = amortisseur), du bruit
idiosyncratique à queues épaisses (Student-t), et un flight-to-quality qui pousse
oblig longues / or / TIPS à la hausse pendant les krachs. Reproduit : forte
corrélation des actifs risqués, décorrélation des amortisseurs, drawdowns de
crise — exactement ce que l'optimiseur doit savoir exploiter.
"""
import numpy as np
import pandas as pd
from . import universe as U

# (mu annuel, vol annuelle, bêta au facteur risque)
_PARAMS = {
    "US_LARGE":   (0.105, 0.17,  1.00),
    "US_SMALL":   (0.115, 0.22,  1.15),
    "DEV_EXUS":   (0.085, 0.18,  0.95),
    "EMERGING":   (0.100, 0.24,  1.10),
    "TREAS_LONG": (0.040, 0.12, -0.35),
    "TREAS_MID":  (0.030, 0.06, -0.18),
    "CORP_IG":    (0.042, 0.07,  0.20),
    "HIGH_YIELD": (0.065, 0.11,  0.60),
    "GOLD":       (0.045, 0.15, -0.10),
    "COMMOD":     (0.028, 0.19,  0.30),
    "REIT":       (0.090, 0.20,  0.80),
    "TIPS":       (0.030, 0.06, -0.08),
}
# amortisseurs qui montent pendant les krachs (flight-to-quality)
_HEDGE = {"TREAS_LONG": 1.0, "TREAS_MID": 0.6, "GOLD": 0.8, "TIPS": 0.4, "CORP_IG": 0.15}
WEEKS = 52.0


def generate(n_weeks=940, seed=20, start="2007-01-05"):
    rng = np.random.default_rng(seed)
    keys = list(_PARAMS.keys())
    n = len(keys)

    # --- facteur de risque commun : vol AR(1) + spikes de crise ---
    base_sd = 0.020                                   # sd hebdo de base du facteur
    logv = np.zeros(n_weeks)
    for t in range(1, n_weeks):
        logv[t] = 0.94 * logv[t - 1] + rng.normal(0, 0.25)   # clustering
    sd = base_sd * np.exp(logv - logv.var() / 2)

    crisis_mean = np.zeros(n_weeks)
    crisis_volx = np.ones(n_weeks)
    fq = np.zeros(n_weeks)                             # intensité flight-to-quality (selloff seul)
    def selloff(a, b, drift, volx, fqx):
        crisis_mean[a:b] += drift
        crisis_volx[a:b] *= volx
        fq[a:b] += fqx
    def rebound(a, b, drift, volx):
        crisis_mean[a:b] += drift
        crisis_volx[a:b] *= volx
    # type 2008 : selloff violent puis reprise → aller-retour (drawdown profond, pas perte permanente)
    selloff(185, 205, -0.028, 3.2, 0.007)
    rebound(205, 245,  0.016, 1.6)
    # type 2020 : krach éclair puis rebond rapide en V
    selloff(640, 649, -0.055, 4.5, 0.013)
    rebound(649, 672,  0.030, 1.8)

    f = rng.normal(crisis_mean, sd * crisis_volx)     # facteur risque hebdo

    # --- rendements par actif ---
    R = np.empty((n_weeks, n))
    for j, k in enumerate(keys):
        mu_a, vol_a, beta = _PARAMS[k]
        mu_w = mu_a / WEEKS
        tgt_var = (vol_a / np.sqrt(WEEKS)) ** 2
        idio_var = max(tgt_var - (beta * base_sd) ** 2, 1e-6)
        idio = rng.standard_t(5, n_weeks) * np.sqrt(idio_var * 3 / 5)  # t(5), var ajustée
        r = mu_w + beta * f + idio
        r += _HEDGE.get(k, 0.0) * fq                  # amortisseurs en crise
        R[:, j] = r

    idx = pd.bdate_range(start=start, periods=n_weeks, freq="W-FRI")
    ret = pd.DataFrame(R, index=idx, columns=keys)
    meta = {
        "source": "SYNTHÉTIQUE (sources live injoignables depuis cette IP)",
        "n_assets": n, "n_weeks": n_weeks,
        "start": str(ret.index.min().date()), "end": str(ret.index.max().date()),
        "years": round(n_weeks / WEEKS, 1),
    }
    return ret, meta
