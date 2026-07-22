"""Conversion des séries de cours en EUR — perspective investisseur euro.

Un fonds valorisé en devise étrangère (GBP, USD, SEK, NOK…) expose l'investisseur
euro au risque de change : sa performance, sa volatilité et surtout son DRAWDOWN
mesurés en EUR incluent les mouvements FX. Optimiser un CDaR sur des séries en
devise native SOUS-ESTIME donc le risque réel (le change ajoute du drawdown non
compté). Ce module ramène toute série dans l'unité du portefeuille : l'EUR.

Source FX : EODHD FOREX (`{CCY}EUR.FOREX` = nombre d'EUR par 1 unité de CCY),
même endpoint /eod que le reste (adjusted_close). Cache local `data/fx/{CCY}EUR.csv`
(« chaque requête nourrit la base », comme les UC). L'EUR est l'identité.

Cas pence (GBX / GBp) : certaines lignes LSE/EUFUND cotent en pence = GBP/100.
On normalise en GBP (÷100) AVANT d'appliquer le taux GBP→EUR — sinon un facteur
100 fausse tout. `normalize_ccy` centralise cette règle.
"""
import os

import pandas as pd

_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "fx")


def normalize_ccy(ccy):
    """Renvoie (devise_canonique, facteur) : prix_en_ccy × facteur = prix_en_canon.

    Seul cas non trivial sur l'univers UE/UK : le pence. EODHD (et le LSE) cotent
    certaines lignes en GBX/GBp = GBP/100 → canon 'GBP', facteur 0.01. Sans cette
    normalisation un facteur 100 fausserait toute la conversion.
    """
    c = (ccy or "").strip().upper()
    if c in ("GBX", "GBP0", "PENCE"):
        return "GBP", 0.01
    return c, 1.0


# ----------------------------------------------------------------------------
# Cœur : conversion (math pure, testable hors réseau)
# ----------------------------------------------------------------------------
def convert(price: pd.Series, fx: pd.Series) -> pd.Series:
    """Prix en devise → prix en EUR. `fx` = EUR par 1 unité de la devise.

    Le taux FX est réindexé sur les dates du prix puis PROPAGÉ (ffill) : un cours
    de fonds sans point FX exact le jour même prend le dernier taux connu — pas
    d'invention de valeur, juste report du taux le plus récent (bfill au tout
    début pour ne pas perdre les premières observations). Renvoie une série
    alignée sur l'index du prix, NaN uniquement si aucun taux n'existe.
    """
    if price is None or len(price) == 0:
        return price
    f = fx.reindex(price.index.union(fx.index)).sort_index().ffill().bfill()
    f = f.reindex(price.index)
    out = price.astype(float) * f.astype(float)
    out.name = price.name
    return out


def to_eur(price: pd.Series, ccy: str, fx_provider=None) -> pd.Series:
    """Ramène une série de cours en EUR selon sa devise.

    ccy : devise native (EUR, GBP, USD, SEK, GBX…). `fx_provider(canon)` renvoie
    la série EUR-par-unité (défaut : `eur_per`, qui fetch+cache EODHD). Le pence
    est normalisé en GBP avant conversion.
    """
    canon, factor = normalize_ccy(ccy)
    p = price.astype(float) * factor if factor != 1.0 else price.astype(float)
    p.name = price.name
    if canon in ("EUR", "", None):
        return p
    provider = fx_provider or eur_per
    fx = provider(canon)
    return convert(p, fx)


# ----------------------------------------------------------------------------
# Provider EODHD FOREX (get-or-fetch, cache CSV)
# ----------------------------------------------------------------------------
def _cache_path(canon):
    return os.path.join(_DIR, f"{canon}EUR.csv")


def _load_cache(canon):
    p = _cache_path(canon)
    if not os.path.exists(p):
        return None
    s = pd.read_csv(p, parse_dates=["date"]).set_index("date")["fx"]
    return s.sort_index()


def _store_cache(canon, s):
    os.makedirs(_DIR, exist_ok=True)
    s.rename("fx").to_frame().to_csv(_cache_path(canon), index_label="date")


def eur_per(canon, refetch=False):
    """Série EUR par 1 unité de `canon` (ex. 'GBP' → ~1.17). Cache-or-fetch EODHD.

    Symbole EODHD : `{canon}EUR.FOREX`. EUR renvoie une constante 1.0 (identité,
    aucun réseau). Réutilise l'ingestion EODHD partagée (token via l'env, jamais
    en clair).
    """
    canon = canon.strip().upper()
    if canon == "EUR":
        return pd.Series(dtype="float64", name="EUREUR")
    if not refetch:
        cached = _load_cache(canon)
        if cached is not None and len(cached):
            return cached
    from . import data_eodhd as DE
    sym = f"{canon}EUR.FOREX"
    s = DE._fetch_one(sym, DE._token(), start="1999-01-01")
    if len(s):
        _store_cache(canon, s)
    return s
