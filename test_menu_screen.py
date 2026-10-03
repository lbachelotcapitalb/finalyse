"""Screening direct du menu d'un contrat (hors-réseau, séries synthétiques)."""
import numpy as np
import pandas as pd

from finalyse import menu_screen as MS
from finalyse import portfolios as P

_IDX = pd.date_range("2006-01-02", periods=4800, freq="B")


def _px(mu, sig, seed, idx=_IDX):
    r = np.random.default_rng(seed).normal(mu, sig, len(idx))
    return pd.Series(100 * np.cumprod(1 + r), index=idx)


MENU = [
    {"isin": "FR0010135103", "label": "Carmignac Patrimoine A EUR Acc"},
    {"isin": "LU0000000001", "label": "Fonds Actions Europe Croissance"},
    {"isin": "LU0000000002", "label": "Fonds Actions Europe Value"},
    {"isin": "FR0000000003", "label": "Amundi Obligations Crédit Euro"},
    {"isin": "FR0000000004", "label": "BNP Paribas Monétaire Court Terme"},
    {"isin": "LU0000000005", "label": "Fonds Récent Actions Monde"},
    {"isin": "LU0000000006", "label": "Fonds Sans Cours"},
]
PRICES = {
    "FR0010135103.EUFUND": _px(0.0002, 0.004, 1),
    "LU0000000001.EUFUND": _px(0.0004, 0.012, 2),
    "LU0000000002.EUFUND": _px(0.0001, 0.012, 3),
    "FR0000000003.EUFUND": _px(0.0001, 0.002, 4),
    "FR0000000004.EUFUND": _px(0.00005, 0.0001, 5),
    "LU0000000005.EUFUND": _px(0.0004, 0.01, 6, pd.date_range("2019-01-01", periods=1700, freq="B")),
}


def _fetch(sym):
    if sym not in PRICES:
        raise RuntimeError("404")
    return PRICES[sym]


def test_classes():
    assert MS.fund_classe("Carmignac Patrimoine A EUR Acc") == "diversifié"
    assert MS.fund_classe("BNP Paribas Monétaire Court Terme") == "monétaire"
    assert MS.fund_classe("Amundi Obligations Crédit Euro") == "oblig"
    assert MS.fund_classe("Comgest Growth Europe") == "actions Europe"
    assert MS.fund_classe("SCPI Primovie") == "immobilier"
    assert MS.fund_classe("Pictet Emerging Markets") == "actions émergents"


def test_screen_menu():
    rows, rejets = MS.screen_menu(MENU, _fetch)
    kept = {r["isin"] for r in rows}
    assert kept == {"FR0010135103", "LU0000000001", "LU0000000002", "FR0000000003"}, kept
    motifs = {r["isin"]: r["motif"] for r in rejets}
    assert motifs["FR0000000004"] == "monétaire"
    assert "2019" in motifs["LU0000000005"]
    assert "indisponibles" in motifs["LU0000000006"]
    eu = sorted((r for r in rows if r["classe"] == "actions Europe"), key=lambda r: -r["score"])
    assert eu[0]["isin"] == "LU0000000001"              # meilleur couple rendement/risque
    picked = P.select_candidates(rows, per_class=1)
    assert len(picked) == 3 and {r["classe"] for r in picked} == {"diversifié", "actions Europe", "oblig"}


if __name__ == "__main__":
    for n in [k for k in list(globals()) if k.startswith("test_")]:
        globals()[n]()
        print(f"OK  {n}")
