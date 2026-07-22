"""Résolution de la devise native par instrument.

Le préfixe ISIN NE donne PAS la devise (une part LU peut être libellée en USD ou
GBP). La seule source fiable est le catalogue de la place : EODHD expose, par
exchange, la liste complète des instruments avec leur `Currency`. Une requête par
place (EUFUND, XETRA, PA, LSE…) suffit à bâtir une map ISIN/Code → devise, cachée
localement (`data/ccy/{EXCHANGE}.csv`). Le parsing/lookup est testable hors-réseau.

Sert de préalable à `fx.to_eur` : screener/optimiser en EUR exige de connaître la
devise de chaque série AVANT de la convertir.
"""
import os

import pandas as pd

_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ccy")


def _s(v):
    """Coercion sûre en str : NaN (float, truthy en Python !) / None → ''."""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def _cache_path(exchange):
    return os.path.join(_DIR, f"{exchange.upper()}.csv")


def _load_cache(exchange):
    p = _cache_path(exchange)
    if not os.path.exists(p):
        return None
    return pd.read_csv(p, dtype=str)


def _store_cache(exchange, df):
    os.makedirs(_DIR, exist_ok=True)
    df.to_csv(_cache_path(exchange), index=False)


def _fetch_symbol_list(exchange):
    """Appelle EODHD /exchange-symbol-list/{EXCHANGE}. Renvoie la liste de dicts
    (Code, Name, Country, Exchange, Currency, Type, Isin). Token via l'env."""
    import json
    import urllib.parse
    import urllib.request

    from . import data_eodhd as DE

    tok = DE._token()
    q = urllib.parse.urlencode({"api_token": tok, "fmt": "json"})
    url = f"https://eodhd.com/api/exchange-symbol-list/{exchange.upper()}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "finalyse/1.0"})
    raw = urllib.request.urlopen(req, timeout=90).read().decode("utf-8")
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise RuntimeError(f"exchange-symbol-list {exchange}: réponse inattendue")
    return rows


def exchange_currencies(exchange, refetch=False):
    """DataFrame [Code, Isin, Currency, Name] pour une place. Cache-or-fetch."""
    if not refetch:
        cached = _load_cache(exchange)
        if cached is not None and len(cached):
            return cached
    rows = _fetch_symbol_list(exchange)
    df = pd.DataFrame(rows)
    keep = [c for c in ("Code", "Isin", "Currency", "Name") if c in df.columns]
    df = df[keep].copy()
    _store_cache(exchange, df)
    return df


def build_maps(exchanges, refetch=False):
    """Concatène plusieurs places en deux dicts de lookup : par ISIN et par Code.
    En cas de doublon d'ISIN sur plusieurs places, la première place l'emporte
    (ordre de `exchanges` = priorité — mettre la place de cotation réelle en tête).
    """
    by_isin, by_code = {}, {}
    for ex in exchanges:
        try:
            df = exchange_currencies(ex, refetch=refetch)
        except Exception as e:  # noqa: BLE001 — une place indispo ne doit pas tout casser
            print(f"  [skip place {ex}] {str(e)[:60]}")
            continue
        for _, r in df.iterrows():
            cur = _s(r.get("Currency")).upper()
            if not cur:
                continue
            isin = _s(r.get("Isin")).upper()
            code = _s(r.get("Code")).upper()
            if isin and isin not in by_isin:
                by_isin[isin] = cur
            if code and code not in by_code:
                by_code[code] = cur
    return by_isin, by_code


def resolve(isin=None, code=None, maps=None, default=None):
    """Devise d'un instrument via (by_isin, by_code). ISIN prioritaire (unique),
    repli sur le code de cotation. `default` si introuvable (à logger, pas à taire).
    """
    by_isin, by_code = maps
    if isin:
        c = by_isin.get(isin.strip().upper())
        if c:
            return c
    if code:
        c = by_code.get(code.strip().upper())
        if c:
            return c
    return default


# Places pertinentes (vérifiées 200 sur le plan EODHD courant), par ordre de
# priorité de résolution : EUFUND (UC AV), puis les places de cotation ETF.
DEFAULT_EXCHANGES = ["EUFUND", "XETRA", "PA", "LSE"]
