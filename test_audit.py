"""Régressions de l'audit du 03/10/2026 (hors-réseau, séries synthétiques).

Chaque test vise un défaut constaté, et échouait sur le code d'avant :
  1. profils jamais testés hors-échantillon ;
  2. contrôle d'honnêteté qui comparait un CDaR 5 ans à un max DD 1 an ;
  4. repli muet (profil inatteignable) et ratio absent qui validait min_cdar ;
  5. fenêtre sans 2008 non signalée ;
  6. HRP qui refranchissait son plafond, min-variance approchée par projection.
"""
import numpy as np
import pandas as pd

from finalyse import backtest as bt
from finalyse import optimize as opt
from finalyse import portfolios as P


def _iid(n_assets=6, T=900, seed=0, start="2001-01-05"):
    rng = np.random.default_rng(seed)
    mu = rng.uniform(0.0003, 0.0018, n_assets)
    sig = rng.uniform(0.008, 0.035, n_assets)
    R = rng.normal(mu, sig, (T, n_assets))
    idx = pd.date_range(start, periods=T, freq="W-FRI")
    return pd.DataFrame(R, index=idx, columns=[f"A{i}" for i in range(n_assets)])


def test_honesty_same_horizon():
    """Sur des rendements i.i.d. (aucun surajustement possible pour 1/N), le
    nouveau ratio vaut ≈ 1 ; l'ancien (CDaR 5 ans au dénominateur) était
    mécaniquement < 1 — c'est le biais d'indulgence corrigé."""
    ret = _iid(seed=1)
    _, folds = bt.walk_forward(ret, "equipondere", train=260, test=52, step=52)
    h = bt.honesty_check(folds)
    assert 0.6 <= h["ratio_realise_sur_promesse"] <= 1.5, h
    assert h["ancien_ratio_cdar_train"] < h["ratio_realise_sur_promesse"], h
    print(f"  ratio horizon égal={h['ratio_realise_sur_promesse']}  ancien={h['ancien_ratio_cdar_train']}")


def test_profiles_are_tested_oos():
    res = P.optimize_envelope(_iid(seed=2), wmax=0.5)
    for name, p in res["profils"].items():
        assert p["oos"] and "max_drawdown" in p["oos"], name
        assert isinstance(p["tient_oos"], bool) and p["motif"], name
        assert p["honnetete"].get("ratio_realise_sur_promesse") is not None, name
    assert res["walk_forward"]["equipondere"]["oos"]
    print("  " + " | ".join(f"{k}: IS {v['in_sample']['cagr']:.1%} → OOS {v['oos']['cagr']:.1%}"
                            for k, v in res["profils"].items()))


def test_unreachable_profile_is_flagged():
    # Cible absurde (0,1 %) : aucun point de frontière ne la tient.
    ret = _iid(seed=3)
    w, ok, mdd = opt.profile_on_frontier(ret.values, 0.001, wmax=0.5)
    assert ok is False and mdd > 0.001
    res = P.optimize_envelope(ret, wmax=0.5, profiles={"impossible": 0.001})
    p = res["profils"]["impossible"]
    assert p["atteignable"] is False and p["tient_oos"] is False
    assert any("impossible" in a for a in res["avertissements"])


def test_missing_ratio_fails_closed(monkeypatch=None):
    orig = bt.honesty_check
    bt.honesty_check = lambda folds: {}
    try:
        res = P.optimize_envelope(_iid(seed=4), wmax=0.5)
    finally:
        bt.honesty_check = orig
    assert res["recommande"]["methode"] == "hrp", res["recommande"]
    assert "non mesurable" in res["recommande"]["motif"]


def test_short_window_warned():
    res = P.optimize_envelope(_iid(T=400, seed=5, start="2019-06-07"), wmax=0.5)
    assert any("2008" in a for a in res["avertissements"]), res["avertissements"]
    res_long = P.optimize_envelope(_iid(T=900, seed=5, start="2001-01-05"), wmax=0.5)
    assert not any("2008" in a for a in res_long["avertissements"])


def test_hrp_respects_cap():
    rng = np.random.default_rng(6)
    sig = np.array([0.002, 0.003, 0.03, 0.04, 0.05])     # 2 lignes très calmes → HRP les gave
    R = rng.normal(0.0005, sig, (600, 5))
    w = opt.hrp(R, wmax=0.30)
    assert abs(w.sum() - 1) < 1e-9 and w.max() <= 0.30 + 1e-9, w
    naive = np.minimum(opt.hrp(R), 0.30)
    naive = naive / naive.sum()
    assert naive.max() > 0.30 + 1e-6, "le cas ne reproduit pas le défaut d'origine"


def test_min_variance_is_true_optimum():
    R = _iid(seed=7).values
    w, _ = opt.min_variance_lw(R, wmax=0.35)
    assert abs(w.sum() - 1) < 1e-9 and w.max() <= 0.35 + 1e-6 and w.min() >= 0
    from sklearn.covariance import LedoitWolf
    cov = LedoitWolf().fit(R).covariance_
    # Aucun portefeuille admissible tiré au hasard ne fait mieux.
    rng = np.random.default_rng(0)
    v = w @ cov @ w
    for _ in range(2000):
        x = opt._project_capped_simplex(rng.dirichlet(np.ones(len(w))), 0.35)
        assert x @ cov @ x >= v - 1e-12


if __name__ == "__main__":
    for name in [n for n in list(globals()) if n.startswith("test_")]:
        globals()[name]()
        print(f"OK  {name}")
    print("Tous les tests d'audit passent.")
