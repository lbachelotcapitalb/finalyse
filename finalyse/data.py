"""Ingestion des cours + nettoyage.

Source proto : Stooq (CSV daily gratuit). Yahoo/yfinance renvoie 429 depuis
cette IP ; Stooq est le fallback EU qui répond. En prod → EODHD (adjusted_close
+ delisted pour traiter le survivorship bias).

Pipeline : fetch -> alignement calendrier -> fenêtre commune -> resample hebdo
(W-FRI) -> rendements simples. On travaille en rendements SIMPLES car le
rendement d'un portefeuille est linéaire en simple (w·R) et le drawdown se
calcule sur l'équité composée — cohérent avec l'optimiseur CDaR.
"""
import io
import time
import urllib.request
import numpy as np
import pandas as pd

_STOOQ = "https://stooq.com/q/d/l/?s={sym}&i=d"


def _fetch_one(sym: str, retries: int = 3) -> pd.Series:
    url = _STOOQ.format(sym=sym)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
            if "Exceeded" in raw or "<html" in raw.lower():
                last = RuntimeError(f"{sym}: réponse invalide Stooq (quota ?)")
                time.sleep(1.5 * (attempt + 1))
                continue
            df = pd.read_csv(io.StringIO(raw))
            if "Close" not in df.columns or len(df) < 50:
                last = RuntimeError(f"{sym}: CSV inattendu ({list(df.columns)})")
                time.sleep(1.0)
                continue
            s = pd.Series(df["Close"].values, index=pd.to_datetime(df["Date"]), name=sym)
            return s.sort_index()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Échec fetch {sym}: {last}")


def load_prices(tickers: dict, pause: float = 0.4, verbose: bool = True) -> pd.DataFrame:
    """tickers: {cle_interne: symbole_stooq} -> DataFrame de clôtures (colonnes = clés)."""
    cols = {}
    for key, sym in tickers.items():
        s = _fetch_one(sym)
        cols[key] = s
        if verbose:
            print(f"  {key:<11} {sym:<8} {len(s):>5} pts  {s.index.min().date()} → {s.index.max().date()}")
        time.sleep(pause)
    px = pd.DataFrame(cols).sort_index()
    return px


def common_window(px: pd.DataFrame) -> pd.DataFrame:
    """Restreint à la fenêtre où TOUTES les séries existent (align. inner)."""
    px = px.dropna(how="all")
    first_valid = px.apply(lambda c: c.first_valid_index()).max()
    out = px.loc[first_valid:].dropna()
    return out


def to_weekly_returns(px: pd.DataFrame) -> pd.DataFrame:
    """Clôtures quotidiennes -> rendements hebdo simples (dernier point de chaque semaine).

    Hebdo : réduit le bruit micro-structure et rend le LP CDaR tractable
    (T ~ 900 obs sur ~18 ans au lieu de ~4500 en daily).
    """
    wk = px.resample("W-FRI").last().dropna()
    ret = wk.pct_change().dropna()
    return ret


def prepare(tickers: dict, verbose: bool = True):
    """Renvoie (returns_hebdo, prix_fenetre_commune, meta)."""
    if verbose:
        print("Ingestion Stooq :")
    px = load_prices(tickers, verbose=verbose)
    pxc = common_window(px)
    ret = to_weekly_returns(pxc)
    meta = {
        "n_assets": ret.shape[1],
        "n_weeks": ret.shape[0],
        "start": str(ret.index.min().date()),
        "end": str(ret.index.max().date()),
        "years": round((ret.index.max() - ret.index.min()).days / 365.25, 1),
    }
    if verbose:
        print(f"Fenêtre commune : {meta['start']} → {meta['end']} "
              f"({meta['years']} ans, {meta['n_weeks']} semaines, {meta['n_assets']} actifs)")
    return ret, pxc, meta
