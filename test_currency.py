"""Tests hors-réseau du résolveur de devises (finalyse.currency).

On stubbe `exchange_currencies` (aucun appel EODHD). On vérifie : réduction
liste→map, priorité ISIN sur code, priorité de la 1re place en cas de doublon,
et le repli `default` quand l'instrument est introuvable.
"""
import pandas as pd

from finalyse import currency as C


def _fake(rows):
    return pd.DataFrame(rows)


def test_resolve_isin_priority():
    maps = ({"GB00B1Y9CB49": "GBP"}, {"GB00B1Y9CB49": "USD"})  # code dit USD, ISIN GBP
    assert C.resolve(isin="GB00B1Y9CB49", code="GB00B1Y9CB49", maps=maps) == "GBP"


def test_resolve_code_fallback():
    maps = ({}, {"GBS": "GBP"})
    assert C.resolve(isin="XX0000000000", code="GBS", maps=maps) == "GBP"


def test_resolve_default():
    maps = ({}, {})
    assert C.resolve(isin="ZZ", code="ZZ", maps=maps, default="EUR") == "EUR"


def test_build_maps_first_exchange_wins(monkeypatch):
    data = {
        "EUFUND": _fake([{"Code": "F1", "Isin": "LU0000000001", "Currency": "USD"}]),
        "XETRA": _fake([{"Code": "F1X", "Isin": "LU0000000001", "Currency": "EUR"}]),
    }
    monkeypatch.setattr(C, "exchange_currencies", lambda ex, refetch=False: data[ex])
    by_isin, by_code = C.build_maps(["EUFUND", "XETRA"])
    assert by_isin["LU0000000001"] == "USD"       # EUFUND (1re) l'emporte
    assert by_code["F1"] == "USD" and by_code["F1X"] == "EUR"


def test_build_maps_skips_empty_currency():
    # sans monkeypatch : on appelle build_maps via un stub manuel
    data = _fake([{"Code": "A", "Isin": "I1", "Currency": ""},
                  {"Code": "B", "Isin": "I2", "Currency": "sek"}])
    C._orig = C.exchange_currencies
    C.exchange_currencies = lambda ex, refetch=False: data
    try:
        by_isin, by_code = C.build_maps(["X"])
    finally:
        C.exchange_currencies = C._orig
    assert "I1" not in by_isin and by_isin["I2"] == "SEK"  # vide ignoré, casse normalisée


if __name__ == "__main__":
    # mini-harness sans pytest (monkeypatch simulé pour le test qui en a besoin)
    class MP:
        def setattr(self, obj, name, val):
            setattr(obj, name, val)

    test_resolve_isin_priority()
    print("OK  test_resolve_isin_priority")
    test_resolve_code_fallback()
    print("OK  test_resolve_code_fallback")
    test_resolve_default()
    print("OK  test_resolve_default")
    test_build_maps_first_exchange_wins(MP())
    print("OK  test_build_maps_first_exchange_wins")
    test_build_maps_skips_empty_currency()
    print("OK  test_build_maps_skips_empty_currency")
    print("Tous les tests currency passent.")
