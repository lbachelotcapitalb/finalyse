"""Tests sanity — verrouillent la correction du moteur (indépendants de la source).
Lancer : python test_sanity.py
"""
import numpy as np
from finalyse import synth, optimize as opt, metrics as m, backtest as bt, montecarlo as mc

ret, _ = synth.generate(seed=1)
R = ret.values
keys = list(ret.columns)
fails = []


def check(name, cond):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}")
    if not cond:
        fails.append(name)


print("Optimiseurs :")
w_mc, cdar_val = opt.min_cdar(R)
check("min_cdar : poids somment à 1", abs(w_mc.sum() - 1) < 1e-6)
check("min_cdar : long-only", (w_mc >= -1e-9).all())
check("min_cdar : respect plafond wmax=0.35", (w_mc <= 0.35 + 1e-6).all())

w_hrp = opt.hrp(R)
check("hrp : poids somment à 1", abs(w_hrp.sum() - 1) < 1e-6)
check("hrp : long-only", (w_hrp >= -1e-9).all())

w_mv, shrink = opt.min_variance_lw(R)
check("minvar_lw : poids somment à 1", abs(w_mv.sum() - 1) < 1e-6)
check("minvar_lw : shrinkage Ledoit-Wolf dans [0,1]", 0 <= shrink <= 1)

# Propriété centrale : le portefeuille min-CDaR doit avoir un drawdown
# strictement inférieur à un portefeuille équipondéré et au benchmark.
r_mc = R @ w_mc
r_eq = R @ (np.ones(R.shape[1]) / R.shape[1])
check("min_cdar : MaxDD < équipondéré", m.max_drawdown(r_mc) < m.max_drawdown(r_eq))
check("min_cdar : CDaR ex-post < équipondéré", m.cdar(r_mc) < m.cdar(r_eq))

# Frontière : le rendement doit croître (au sens large) avec le budget drawdown.
front = opt.drawdown_frontier(R, n_points=8)
cagrs = [m.cagr(R @ p["weights"]) for p in front]
mdds = [m.max_drawdown(R @ p["weights"]) for p in front]
check("frontière : >= 4 points faisables", len(front) >= 4)
check("frontière : rendement croît avec le drawdown (corr > 0)",
      np.corrcoef(mdds, cagrs)[0, 1] > 0)

print("Contrainte de budget CDaR :")
w_b, hit = opt.max_return_under_cdar(R, cdar_budget=0.05)
check("max_return_under_cdar : CDaR atteint <= budget (+tol)", hit <= 0.05 + 1e-4)

print("Walk-forward & Monte-Carlo :")
oos, folds = bt.walk_forward(ret, "min_cdar")
check("walk_forward : produit des folds OOS", len(folds) > 0 and len(oos) > 0)
proj = mc.project(r_mc, horizon_years=5, n_sims=200)
check("monte_carlo : médiane multiple > 1", proj["multiple_terminal"]["p50"] > 1)
check("monte_carlo : p95 MaxDD dans [0,1]", 0 <= proj["max_drawdown"]["p95"] <= 1)

print()
if fails:
    print(f"ÉCHECS : {len(fails)} → {fails}")
    raise SystemExit(1)
print("Tous les tests sanity passent.")
