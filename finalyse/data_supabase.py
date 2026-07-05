"""Lecture des cours depuis Supabase (finalyse.prices) — ferme la boucle.

EODHD → sync → Supabase → CE module → moteur → dashboard. Le backtest ne
dépend plus du token EODHD : seul le sync l'utilise. Clé lue dans l'env
SUPABASE_KEY (anon si policy select en place) ou SUPABASE_SERVICE_KEY (backend).
"""
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import pandas as pd
from . import data as D

PAGE = 1000  # Supabase plafonne PostgREST à 1000 lignes/réponse → pagination


def _key():
    k = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
    if not k:
        raise RuntimeError("SUPABASE_KEY ou SUPABASE_SERVICE_KEY absent de l'env.")
    return k


def _get(path):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = _key()
    req = urllib.request.Request(url, headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Accept-Profile": "finalyse"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Supabase GET /{path.split('?')[0]} → HTTP {e.code}: "
                           f"{e.read().decode('utf-8','replace')[:300]}")


def _series(symbol):
    rows, off = [], 0
    while True:
        page = _get(f"prices?symbol=eq.{urllib.parse.quote(symbol)}"
                    f"&select=date,adjusted_close&order=date.asc&limit={PAGE}&offset={off}")
        rows += page
        if len(page) < PAGE:
            break
        off += PAGE
    idx = pd.to_datetime([r["date"] for r in rows])
    return pd.Series([r["adjusted_close"] for r in rows], index=idx, name=symbol, dtype="float64")


def prepare(symbols_map, verbose=True):
    """symbols_map: {cle_interne: symbole} -> (returns_hebdo, prix, meta). Même contrat que data.prepare."""
    if verbose:
        print("Lecture des cours depuis Supabase (finalyse.prices) :")
    cols = {}
    for key, sym in symbols_map.items():
        s = _series(sym)
        cols[key] = s
        if verbose:
            print(f"  {key:<12} {sym:<20} {len(s):>5} pts")
    px = pd.DataFrame(cols).sort_index()
    pxc = D.common_window(px)
    ret = D.to_weekly_returns(pxc)
    meta = {"source": "Supabase (finalyse.prices)", "n_assets": ret.shape[1],
            "n_weeks": ret.shape[0], "start": str(ret.index.min().date()),
            "end": str(ret.index.max().date()),
            "years": round((ret.index.max() - ret.index.min()).days / 365.25, 1)}
    if verbose:
        print(f"Fenêtre commune : {meta['start']} → {meta['end']} ({meta['years']} ans)")
    return ret, pxc, meta
