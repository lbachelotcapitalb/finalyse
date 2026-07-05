"""Registre de sources multi-fournisseurs.

Pour un fonds (ISIN), tente en cascade de récupérer la série la plus profonde,
et rapporte la COUVERTURE (réel vs à reconstruire) :

  1. EODHD (.EUFUND / .US / …) — licencié, quotidien. Primaire.
  2. Résolveur Boursorama : ISIN → identifiant Morningstar (0P…). Sert à
     identifier le fonds même quand la VL n'est pas récupérable (Morningstar est
     derrière un token tournant → flux licencié requis : Quantalys Pôle Data /
     Morningstar Direct). Marqueur pour brancher un adaptateur licencié plus tard.
  3. Sinon → RECONSTRUCTION factorielle (voir reconstruct.py).

Les fonds semi-liquides (OPCI, SCPI, infra non coté) tombent presque toujours en
(3) : pas de VL de marché, et leur VL d'expert serait de toute façon lissée.
"""
import re
import urllib.request
import urllib.parse
from . import data_eodhd as DE

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
EODHD_SUFFIXES = ("EUFUND", "US", "PA", "XETRA", "LSE")


def eodhd_fetch(isin_or_symbol, start="1999-01-01", min_points=100):
    """Tente EODHD sur plusieurs places. Renvoie (symbole, série hebdo) ou (None, None)."""
    cands = ([isin_or_symbol] if "." in isin_or_symbol
             else [f"{isin_or_symbol}.{s}" for s in EODHD_SUFFIXES])
    for sym in cands:
        try:
            s = DE._fetch_one(sym, DE._token(), start=start)
            if len(s) >= min_points:
                return sym, s.resample("W-FRI").last().pct_change(fill_method=None).dropna()
        except Exception:
            continue
    return None, None


def resolve_boursorama(isin):
    """ISIN → identifiant Morningstar (0P…) via la recherche Boursorama.
    Identifie le fonds pour un futur adaptateur licencié. Renvoie l'id ou None.
    """
    try:
        url = f"https://www.boursorama.com/recherche/ajax?query={urllib.parse.quote(isin)}"
        html = urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=15).read().decode("utf-8", "replace")
        m = re.search(r"/bourse/[a-z]+/cours/([A-Za-z0-9]+)/", html)
        return m.group(1) if m else None
    except Exception:
        return None


def coverage(isins, verbose=True):
    """Pour une liste d'ISIN : où on peut sourcer, et où il faut reconstruire.
    Renvoie {isin: {'source','symbol','weeks','morningstar','method'}}.
    """
    out = {}
    for isin, name in (isins.items() if isinstance(isins, dict) else [(i, "") for i in isins]):
        sym, ser = eodhd_fetch(isin)
        if sym:
            rec = {"source": "EODHD", "symbol": sym, "weeks": len(ser),
                   "morningstar": None, "method": "réel"}
        else:
            ms = resolve_boursorama(isin)
            rec = {"source": "aucune (marché)", "symbol": None, "weeks": 0,
                   "morningstar": ms, "method": "RECONSTRUCTION factorielle"}
        out[isin] = rec
        if verbose:
            tag = (f"EODHD {rec['symbol']} ({rec['weeks']} sem.)" if rec["source"] == "EODHD"
                   else f"à reconstruire — Morningstar {rec['morningstar'] or '?'}")
            print(f"  {isin}  {name[:26]:<26} {tag}")
    return out
