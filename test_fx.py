"""Tests hors-réseau de la conversion EUR (finalyse.fx).

On stubbe le provider FX : aucune dépendance EODHD. On vérifie l'identité EUR,
la conversion GBP/USD, la normalisation du pence, l'alignement/ffill du taux, et
surtout que le change INJECTE du drawdown qu'une série en devise native masque —
la raison d'être du module.
"""
import numpy as np
import pandas as pd

from finalyse import fx
from finalyse import metrics as m


def _days(n, start="2010-01-01"):
    return pd.date_range(start, periods=n, freq="D")


def _const_fx(rate):
    return lambda canon: pd.Series(rate, index=_days(400), name=f"{canon}EUR")


def test_eur_identity():
    idx = _days(10)
    p = pd.Series(np.linspace(100, 110, 10), index=idx, name="X")
    out = fx.to_eur(p, "EUR", fx_provider=_const_fx(999))  # provider ignoré
    assert np.allclose(out.values, p.values)


def test_gbp_constant():
    idx = _days(5)
    p = pd.Series([100.0] * 5, index=idx, name="X")
    out = fx.to_eur(p, "GBP", fx_provider=_const_fx(1.2))
    assert np.allclose(out.values, 120.0)


def test_pence_normalisation():
    # 1000 GBX = 10 GBP ; à 1.2 EUR/GBP → 12 EUR
    idx = _days(5)
    p = pd.Series([1000.0] * 5, index=idx, name="X")
    out = fx.to_eur(p, "GBX", fx_provider=_const_fx(1.2))
    assert np.allclose(out.values, 12.0), out.values


def test_ffill_sparse_fx():
    # prix quotidien, FX seulement 2 points → report du dernier taux connu
    idx = _days(10)
    p = pd.Series([100.0] * 10, index=idx, name="X")
    fx_sparse = pd.Series([1.0, 1.5], index=[idx[0], idx[4]], name="GBPEUR")
    out = fx.convert(p, fx_sparse)
    # avant le 2e point : 1.0 ; à partir du 5e jour : 1.5 (ffill)
    assert np.isclose(out.iloc[0], 100.0)
    assert np.isclose(out.iloc[3], 100.0)
    assert np.isclose(out.iloc[4], 150.0)
    assert np.isclose(out.iloc[-1], 150.0)
    assert not out.isna().any()


def test_fx_injects_drawdown():
    # Fonds PLAT en devise native (aucun drawdown) mais la devise chute de 30%.
    # En EUR, l'investisseur subit bien un drawdown ~30% : c'est ce que le module
    # doit révéler et que le screening en devise native masquait.
    idx = _days(300)
    p = pd.Series(100.0, index=idx, name="FUND")  # NAV plate
    fx_rate = pd.Series(np.concatenate([np.linspace(1.2, 1.2, 150),
                                        np.linspace(1.2, 0.84, 150)]), index=idx)
    eur = fx.convert(p, fx_rate)
    r_native = p.resample("W-FRI").last().pct_change().dropna().values
    r_eur = eur.resample("W-FRI").last().pct_change().dropna().values
    assert m.max_drawdown(r_native) < 1e-9          # natif : aucun drawdown
    assert m.max_drawdown(r_eur) > 0.25             # EUR : ~30% de drawdown FX
    print(f"  maxdd natif={m.max_drawdown(r_native):.3f}  EUR={m.max_drawdown(r_eur):.3f}")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK  {name}")
    print("Tous les tests fx passent.")
