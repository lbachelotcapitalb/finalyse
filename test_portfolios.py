"""Smoke-test hors-réseau du driver par enveloppe (finalyse.portfolios).

Fetcher et provider FX stubbés (séries synthétiques déterministes) : on valide le
CÂBLAGE complet — fetch → devise → conversion EUR → fenêtre commune → min_cdar/HRP —
sans toucher au réseau. Vérifie aussi que la conversion EUR change bien les poids
vs une optim en devise native (preuve que le change entre dans le CDaR).
"""
import numpy as np
import pandas as pd

from finalyse import portfolios as P


RNG = np.random.default_rng(42)
_IDX = pd.date_range("2006-01-01", periods=1000, freq="B")  # ~4 ans ouvrés, couvre 2008


def _walk(mu, sig, seed):
    r = np.random.default_rng(seed).normal(mu, sig, len(_IDX))
    return pd.Series(100 * np.cumprod(1 + r), index=_IDX)


# Univers synthétique : 3 classes, séries en devises variées
_PRICES = {
    "IE00AAA.EUFUND": _walk(0.0004, 0.011, 1),   # actions US (en USD)
    "LU00BBB.EUFUND": _walk(0.0003, 0.009, 2),   # actions EU (en EUR)
    "GB00CCC.EUFUND": _walk(0.0002, 0.006, 3),   # oblig (en GBP)
    "IE00DDD.EUFUND": _walk(0.0003, 0.012, 4),   # actions US (en USD)
}
_CCY = {"IE00AAA": "USD", "LU00BBB": "EUR", "GB00CCC": "GBP", "IE00DDD": "USD"}
_ROWS = [
    {"isin": "IE00AAA", "code": "AAA", "name": "US A", "classe": "actions US", "score": "0.9", "years": "4"},
    {"isin": "LU00BBB", "code": "BBB", "name": "EU B", "classe": "actions EU", "score": "0.8", "years": "4"},
    {"isin": "GB00CCC", "code": "CCC", "name": "Oblig C", "classe": "oblig", "score": "0.7", "years": "4"},
    {"isin": "IE00DDD", "code": "DDD", "name": "US D", "classe": "actions US", "score": "0.6", "years": "4"},
]


def _fetcher(sym):
    return _PRICES[sym]


def _fx_provider(canon):
    # Taux VARIABLE dans le temps (le FX réel a sa propre vol → il injecte du
    # drawdown). Un taux constant serait invariant sur les rendements (aucun effet).
    base = {"USD": 0.90, "GBP": 1.18, "SEK": 0.088}.get(canon, 1.0)
    idx = pd.date_range("2005-01-01", periods=2500, freq="D")
    if canon == "EUR":
        return pd.Series(dtype="float64")
    seed = {"USD": 11, "GBP": 12, "SEK": 13}.get(canon, 14)
    steps = np.random.default_rng(seed).normal(0, 0.004, len(idx))
    return pd.Series(base * np.cumprod(1 + steps), index=idx)


def test_load_eur_returns_wires_end_to_end():
    maps = ({k: v for k, v in _CCY.items()}, {})
    ret, kept = P.load_eur_returns(_ROWS, "AV", maps=maps, fx_provider=_fx_provider,
                                   fetcher=_fetcher, verbose=False)
    assert ret.shape[1] == 4 and ret.shape[0] > 100
    ccys = {i["key"]: i["ccy"] for i in kept}
    assert ccys["IE00AAA"] == "USD" and ccys["LU00BBB"] == "EUR"
    print(f"  fenêtre {ret.index.min().date()}→{ret.index.max().date()}  {ret.shape}")


def test_optimize_envelope_valid():
    maps = ({k: v for k, v in _CCY.items()}, {})
    ret, _ = P.load_eur_returns(_ROWS, "AV", maps=maps, fx_provider=_fx_provider,
                                fetcher=_fetcher, verbose=False)
    res = P.optimize_envelope(ret, wmax=0.5)
    w = res["min_cdar"]["poids"]
    assert abs(sum(w.values()) - 1.0) < 1e-6, w
    assert all(0 <= v <= 0.5 + 1e-9 for v in w.values())
    assert res["hrp"]["poids"] and res["profils"]["equilibre"]["poids"]
    assert res["min_cdar"]["in_sample"]["cdar95"] >= 0
    print(f"  min_cdar poids={w}")
    print(f"  cdar95={res['min_cdar']['in_sample']['cdar95']}  maxdd={res['min_cdar']['in_sample']['max_drawdown']}")


def test_eur_conversion_changes_allocation():
    # Optim EN EUR vs optim si l'on ignorait le change (tout en 'EUR' → natif).
    maps_eur = ({k: v for k, v in _CCY.items()}, {})
    maps_native = ({k: "EUR" for k in _CCY}, {})
    ret_eur, _ = P.load_eur_returns(_ROWS, "AV", maps=maps_eur, fx_provider=_fx_provider,
                                    fetcher=_fetcher, verbose=False)
    ret_nat, _ = P.load_eur_returns(_ROWS, "AV", maps=maps_native, fx_provider=_fx_provider,
                                    fetcher=_fetcher, verbose=False)
    w_eur = P.optimize_envelope(ret_eur, wmax=0.5)["min_cdar"]["poids"]
    w_nat = P.optimize_envelope(ret_nat, wmax=0.5)["min_cdar"]["poids"]
    # Les allocations diffèrent : la prise en compte du change modifie le CDaR.
    diff = sum(abs(w_eur.get(k, 0) - w_nat.get(k, 0)) for k in set(w_eur) | set(w_nat))
    assert diff > 1e-3, f"conversion sans effet (diff={diff})"
    print(f"  Δallocation EUR vs natif = {diff:.3f}")


def test_select_candidates_diversifies():
    picked = P.select_candidates(_ROWS, per_class=1)
    classes = {r["classe"] for r in picked}
    assert classes == {"actions US", "actions EU", "oblig"}
    us = [r for r in picked if r["classe"] == "actions US"]
    assert len(us) == 1 and us[0]["code"] == "AAA"  # meilleur score gardé


def test_exotic_commodity_filter():
    # Exclus (mono-matière / secteur étroit)
    for n in ["WisdomTree Live Cattle EUR", "WisdomTree Copper ETC",
              "WisdomTree Soybeans EUR", "WisdomTree Gasoline EUR",
              "WisdomTree Physical Silver EUR", "WisdomTree Physical Palladium EUR",
              "WisdomTree Agriculture EUR", "WisdomTree Softs EUR"]:
        assert P.is_exotic_commodity(n), f"devrait être exclu : {n}"
    # Conservés (or + paniers larges + non-matières)
    for n in ["Gold Bullion Securities ETC", "WisdomTree Physical Gold EUR",
              "Lyxor Commodities Refinitiv/CoreCommodity CRB TR UCITS",
              "Market Access Rogers International Commodity Index UCITS",
              "iShares Core S&P 500 UCITS", "Amundi Euro Government Bond"]:
        assert not P.is_exotic_commodity(n), f"devrait être gardé : {n}"


def test_annual_fee():
    idx = pd.date_range("2020-01-01", periods=53, freq="W-FRI")
    r = pd.DataFrame({"a": [0.0] * 53}, index=idx)  # rendement brut nul
    net = P.apply_annual_fee(r, 0.012)              # 1,2 %/an de frais
    # 52 semaines de frais composés ≈ −1,2 % sur l'année
    cum = float((1.0 + net["a"]).prod() - 1.0)
    assert abs(cum - (-0.012)) < 1e-4, cum
    # frais nul = identité
    assert P.apply_annual_fee(r, 0.0).equals(r)


def test_pea_classe():
    cases = {
        "Amundi ETF PEA Nasdaq-100 UCITS ETF": "actions US",
        "Lyxor PEA S&P 500 UCITS C": "actions US",
        "Amundi ETF PEA MSCI Europe UCITS ETF": "actions Europe",
        "Amundi ETF PEA Japan Topix UCITS ETF EUR": "actions Japon",
        "Amundi ETF PEA MSCI Emerging Markets UCITS ETF": "actions émergents/thème",
        "Lyxor PEA Inde (MSCI India) UCITS ETF Capi": "actions émergents/thème",
        "Amundi PEA Immobilier Europe (FTSE EPRA/NAREIT) UCITS": "immobilier",
        "Amundi PEA Euro Court Terme UCITS ETF": "monétaire",
    }
    for name, expect in cases.items():
        got = P.pea_classe(name)
        assert got == expect, f"{name} → {got} (attendu {expect})"


if __name__ == "__main__":
    for name in ["test_load_eur_returns_wires_end_to_end", "test_optimize_envelope_valid",
                 "test_eur_conversion_changes_allocation", "test_select_candidates_diversifies",
                 "test_exotic_commodity_filter", "test_annual_fee", "test_pea_classe"]:
        globals()[name]()
        print(f"OK  {name}")
    print("Tous les tests portfolios passent.")
