"""Adaptateur de données EODHD (source prod).

Plan « EOD Historical Data – All World » : 30+ ans, mondial, coté + fonds par
ISIN, `adjusted_close` (total return, règle le piège dividendes). Le token est
lu dans l'env `EODHD_API_TOKEN` — JAMAIS en argument, jamais loggué, jamais
imprimé. Coté = symbole `TICKER.US` ; fonds/UC = `ISIN.EUFUND` (à tester).

Cet adaptateur partage le nettoyage (fenêtre commune, returns hebdo) avec
`data.py` : seule l'ingestion change selon la source.
"""
import os
import time
import json
import urllib.request
import urllib.parse
import pandas as pd
from . import data as D

_EOD = "https://eodhd.com/api/eod/{sym}"


def _token():
    tok = os.environ.get("EODHD_API_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("EODHD_API_TOKEN absent de l'environnement "
                           "(injecter via ask-secret.sh, jamais en clair).")
    return tok


def _fetch_one(sym, token, start="2005-01-01", retries=3):
    q = urllib.parse.urlencode({"api_token": token, "fmt": "json",
                                "from": start, "period": "d"})
    url = f"{_EOD.format(sym=sym)}?{q}"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "finalyse/1.0"})
            raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
            rows = json.loads(raw)
            if not isinstance(rows, list):
                # un dict = message d'erreur EODHD ; une liste (même courte/vide) est valide
                last = RuntimeError(f"{sym}: réponse inattendue ({type(rows).__name__})")
                time.sleep(1.0); continue
            if not rows:                       # incrémental à jour : 0 nouvelle ligne = normal
                return pd.Series([], index=pd.to_datetime([]), name=sym, dtype="float64")
            dates = [r["date"] for r in rows]
            # adjusted_close = total return (dividendes réinvestis) ; fallback close
            vals = [r.get("adjusted_close", r.get("close")) for r in rows]
            s = pd.Series(vals, index=pd.to_datetime(dates), name=sym, dtype="float64")
            return s.sort_index()
        except urllib.error.HTTPError as e:  # noqa
            # 401/403 = token ; 404 = symbole inconnu → ne pas réessayer inutilement
            raise RuntimeError(f"{sym}: HTTP {e.code} (token ou symbole ?)")
        except Exception as e:  # noqa: BLE001
            last = e; time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Échec fetch EODHD {sym}: {last}")


def load_prices(symbols, start="2005-01-01", verbose=True):
    """symbols: {cle_interne: symbole_EODHD} -> DataFrame de cours ajustés."""
    token = _token()
    cols = {}
    for key, sym in symbols.items():
        s = _fetch_one(sym, token, start=start)
        cols[key] = s
        if verbose:
            print(f"  {key:<11} {sym:<14} {len(s):>5} pts  {s.index.min().date()} → {s.index.max().date()}")
        time.sleep(0.15)
    return pd.DataFrame(cols).sort_index()


def prepare(symbols, start="2005-01-01", verbose=True):
    """Renvoie (returns_hebdo, prix_fenetre_commune, meta) — même contrat que data.prepare."""
    if verbose:
        print("Ingestion EODHD (adjusted_close) :")
    px = load_prices(symbols, start=start, verbose=verbose)
    pxc = D.common_window(px)
    ret = D.to_weekly_returns(pxc)
    meta = {
        "source": "EODHD (adjusted_close, total return)",
        "n_assets": ret.shape[1], "n_weeks": ret.shape[0],
        "start": str(ret.index.min().date()), "end": str(ret.index.max().date()),
        "years": round((ret.index.max() - ret.index.min()).days / 365.25, 1),
    }
    if verbose:
        print(f"Fenêtre commune : {meta['start']} → {meta['end']} "
              f"({meta['years']} ans, {meta['n_weeks']} sem., {meta['n_assets']} actifs)")
    return ret, pxc, meta


def search(query, limit=8):
    """Recherche l'univers EODHD par nom (fonds/UC françaises → ISIN + symbole).
    Renvoie la liste brute [{Code, Exchange, Name, Type, Country, Currency, ISIN}...].
    Plus fiable que deviner l'ISIN : on interroge directement le catalogue EODHD.
    """
    token = _token()
    q = urllib.parse.urlencode({"api_token": token, "limit": limit})
    url = f"https://eodhd.com/api/search/{urllib.parse.quote(query)}?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "finalyse/1.0"})
    try:
        raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
        return json.loads(raw)
    except urllib.error.HTTPError as e:  # noqa
        raise RuntimeError(f"search '{query}': HTTP {e.code}")


def history_depth(symbol, start="1990-01-01"):
    """Profondeur d'historique NAV/cours dispo pour un symbole EODHD."""
    s = _fetch_one(symbol, _token(), start=start, retries=1)
    return {"points": len(s), "start": str(s.index.min().date()),
            "end": str(s.index.max().date()),
            "annees": round((s.index.max() - s.index.min()).days / 365.25, 1)}


def coverage_check(isins, kind="EUFUND", start="2015-01-01"):
    """Teste la couverture EODHD sur une liste d'ISIN (UC d'assurance-vie).
    Renvoie {isin: {'ok': bool, 'points': n, 'start': date, 'end': date} | erreur}.
    kind : suffixe marché EODHD pour les fonds européens (souvent 'EUFUND').
    """
    token = _token()
    out = {}
    for isin in isins:
        sym = f"{isin}.{kind}"
        try:
            s = _fetch_one(sym, token, start=start, retries=1)
            out[isin] = {"ok": True, "points": len(s),
                         "start": str(s.index.min().date()), "end": str(s.index.max().date())}
        except Exception as e:  # noqa: BLE001
            out[isin] = {"ok": False, "erreur": str(e)[:80]}
        time.sleep(0.15)
    return out
