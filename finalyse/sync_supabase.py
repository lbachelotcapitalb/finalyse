"""Sync incrémental EODHD → Supabase (à lancer par un cron quotidien).

On ne scrape jamais en live : ce script alimente la base, l'app lit la base.
Idempotent : upsert sur (symbol, date), donc rejouable sans doublon.

Env requis (jamais en argument, jamais loggué) :
  EODHD_API_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY

Usage : python -m finalyse.sync_supabase [--full] [--universe deep|ucits|uc|etf_us|all]
"""
import os
import sys
import time
import json
import urllib.request
import urllib.parse
from . import universe as U
from . import data_eodhd as DE

CHUNK = 500  # lignes par POST PostgREST


def _sb(path, method="GET", body=None, prefer=None):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json", "Content-Profile": "finalyse",
               "Accept-Profile": "finalyse"}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw.strip() else None


def _universe_symbols(name):
    if name == "deep":
        return {v: k for k, v in U.DEEP_HISTORY.items()}
    if name == "ucits":
        return {v: k for k, v in U.UCITS_SYMBOLS.items()}
    if name == "uc":
        return {v: k for k, v in U.UC_SYMBOLS.items()}
    if name == "etf_us":
        return {t.upper(): k for k, t in U.TICKERS.items()}
    raise ValueError(name)


def _label(key):
    return {**U.LABELS, **U.UC_LABELS}.get(key, key)


def upsert_instruments(sym_to_key, universe_name):
    rows = [{"symbol": s, "key": k, "label": _label(k),
             "asset_class": U.CLASSES.get(k), "universe": [universe_name],
             "isin": s.split(".")[0] if s.endswith(".EUFUND") else None}
            for s, k in sym_to_key.items()]
    _sb("instruments", "POST", rows, prefer="resolution=merge-duplicates,return=minimal")


def last_date(symbol):
    r = _sb(f"prices?symbol=eq.{urllib.parse.quote(symbol)}&select=date&order=date.desc&limit=1")
    return r[0]["date"] if r else None


def sync(universe_name="deep", full=False):
    sym_to_key = _universe_symbols(universe_name)
    upsert_instruments(sym_to_key, universe_name)
    total = 0
    for sym in sym_to_key:
        start = "1999-01-01" if full else (last_date(sym) or "1999-01-01")
        try:
            s = DE._fetch_one(sym, DE._token(), start=start)
        except Exception as e:  # noqa: BLE001
            print(f"  {sym}: skip ({str(e)[:50]})")
            continue
        rows = [{"symbol": sym, "date": d.strftime("%Y-%m-%d"), "adjusted_close": float(v)}
                for d, v in s.items() if v == v]  # v==v : écarte les NaN
        for i in range(0, len(rows), CHUNK):
            _sb("prices", "POST", rows[i:i + CHUNK],
                prefer="resolution=merge-duplicates,return=minimal")
        total += len(rows)
        print(f"  {sym:<20} +{len(rows)} lignes (depuis {start})")
        time.sleep(0.15)
    _sb("sync_log", "POST", [{"universe": universe_name, "n_symbols": len(sym_to_key),
                              "n_rows": total, "ok": True, "detail": f"full={full}"}],
        prefer="return=minimal")
    print(f"Sync '{universe_name}' terminé : {total} lignes.")
    return total


if __name__ == "__main__":
    full = "--full" in sys.argv
    uni = sys.argv[sys.argv.index("--universe") + 1] if "--universe" in sys.argv else "deep"
    for miss in ("EODHD_API_TOKEN", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        if not os.environ.get(miss):
            sys.exit(f"Env manquant : {miss}")
    if uni == "all":
        for u in ("deep", "ucits", "uc"):
            sync(u, full=full)
    else:
        sync(uni, full=full)
