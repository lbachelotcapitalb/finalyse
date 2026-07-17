"""Régression du backfill calibré (couple_spliced) — offline, synthétique.

Vérifie les deux propriétés qui font la valeur de la méthode :
  1. le RÉCENT est la vraie série du fonds, à l'identique (splice) ;
  2. le PASSÉ PROFOND garde la crise portée par le proxy, à l'échelle du β réel
     estimé sur le recouvrement (pas le β=1 naïf).
"""
import numpy as np
import pandas as pd

from finalyse.reconstruct import couple_spliced


def _data():
    idx = pd.date_range("2010-01-01", periods=500, freq="W-FRI")
    rng = np.random.default_rng(0)
    proxy = pd.Series(rng.normal(0.001, 0.02, 500), index=idx)
    proxy.iloc[20:40] -= 0.03                      # crise dans le passé profond
    real_idx = idx[-200:]                          # le réel n'existe que sur 200 sem.
    real = 0.6 * proxy.loc[real_idx] + 0.0005 + pd.Series(rng.normal(0, 0.005, 200), index=real_idx)
    return proxy, real, real_idx


def test_splice_colle_le_reel():
    proxy, real, real_idx = _data()
    out, meta = couple_spliced(proxy, real, fee_annual=0.0)
    assert out.index.min() == proxy.index.min() and out.index.max() == proxy.index.max()
    assert np.allclose(out.loc[real_idx].values, real.values)     # récent = réel exact
    assert meta["debut_reel"] == str(real_idx.min().date())


def test_splice_calibre_le_beta_et_garde_la_crise():
    proxy, real, real_idx = _data()
    out, meta = couple_spliced(proxy, real, fee_annual=0.0)
    assert 0.4 < meta["beta"] < 0.8                              # β réel ~0.6, pas 1.0
    assert meta["r2"] > 0.5 and meta["confiance"] > 40
    deep = out[out.index < real_idx.min()]
    eq = (1 + deep).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    assert dd < -0.05                                            # la crise profonde est bien là


def test_repli_si_reel_insuffisant():
    proxy, _, _ = _data()
    short = pd.Series([0.01, -0.01, 0.0], index=proxy.index[-3:])
    out, meta = couple_spliced(proxy, short)
    assert len(out) == len(proxy) and meta["confiance"] == 0     # repli calibration de niveau


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f):
            f(); print("OK", n)
    print("tous les tests splice passent")
