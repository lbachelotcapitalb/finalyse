"""Cache local des séries d'UC scrappées — pour ne plus re-scrapper.

Principe demandé : **chaque requête sur une UC nourrit la base**. On expose un
`get_uc_series(isin)` qui :
  1. rend la série du cache si elle existe et n'est pas périmée ;
  2. sinon la récupère (Quantalys), la STOCKE, puis la rend.

Backend actuel = fichiers locaux (`data/uc/{ISIN}.csv` + `data/uc/_manifest.json`),
robuste et sans dépendance. Le backend durable/partagé (Supabase, puis exposition
MCP publique) se branchera derrière la même interface plus tard — voir `push_supabase`
(stub) : la base partagée est le « à voir plus tard » de Léo.
"""
import json
import os

import pandas as pd

_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uc")
_MANIFEST = os.path.join(_DIR, "_manifest.json")


def _load_manifest():
    if os.path.exists(_MANIFEST):
        with open(_MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_manifest(m):
    os.makedirs(_DIR, exist_ok=True)
    with open(_MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def _path(isin):
    return os.path.join(_DIR, f"{isin.strip().upper()}.csv")


def has(isin):
    return os.path.exists(_path(isin))


def list_uc():
    """Manifeste : ce que la base contient déjà."""
    return _load_manifest()


def store_uc_series(isin, base100, meta=None, fetched_on=None):
    """Écrit la série (Series base 100) + met à jour le manifeste. `fetched_on` =
    date ISO (fournie par l'appelant ; pas d'horloge ici pour rester déterministe)."""
    isin = isin.strip().upper()
    os.makedirs(_DIR, exist_ok=True)
    base100.rename("base100").to_frame().to_csv(_path(isin), index_label="date")
    m = _load_manifest()
    entry = {"isin": isin, "points": int(len(base100)),
             "from": str(base100.index[0].date()) if len(base100) else None,
             "to": str(base100.index[-1].date()) if len(base100) else None,
             "fetched_on": fetched_on}
    if meta:
        entry.update({k: v for k, v in meta.items() if k in ("source", "fund_id", "nom")})
    m[isin] = entry
    _save_manifest(m)
    return entry


def load_uc_series(isin):
    """Série base 100 depuis le cache (KeyError si absente)."""
    p = _path(isin)
    if not os.path.exists(p):
        raise KeyError(f"{isin} absent du cache.")
    s = pd.read_csv(p, parse_dates=["date"]).set_index("date")["base100"]
    return s.sort_index()


def get_uc_series(isin, fetcher=None, fetched_on=None, refetch=False):
    """Get-or-fetch. Rend (base100, meta, from_cache).

    fetcher(isin) -> (base100, meta) : appelé sur cache-miss (ex.
    `finalyse.data_quantalys.fetch_uc`). Sans fetcher, lève KeyError sur miss.
    refetch=True force la mise à jour (nourrit la base même si déjà présente).
    """
    isin = isin.strip().upper()
    if has(isin) and not refetch:
        return load_uc_series(isin), _load_manifest().get(isin, {}), True
    if fetcher is None:
        raise KeyError(f"{isin} absent du cache et aucun fetcher fourni.")
    base, meta = fetcher(isin)
    store_uc_series(isin, base, meta, fetched_on=fetched_on)
    return base, meta, False


def push_supabase(isin, base100, meta=None, chunk=800):
    """Backend durable/partagé (Supabase bwealthy, schéma finalyse). Stocke l'UC
    comme un instrument `{ISIN}.QUANTALYS` + sa série base-100 dans `prices`
    (upsert idempotent). Le moteur la relit ensuite via data_supabase.prepare.

    Env : SUPABASE_URL + SUPABASE_SERVICE_KEY (via bw-get, jamais en clair). Data
    Quantalys sous licence → base PRIVÉE ; exposition MCP publique = décision à part.
    """
    import json
    import urllib.request

    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_KEY/KEY absent de l'env.")
    isin = isin.strip().upper()
    symbol = f"{isin}.QUANTALYS"

    def _post(path, rows):
        req = urllib.request.Request(
            f"{base}/rest/v1/{path}", data=json.dumps(rows).encode(), method="POST",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "Content-Profile": "finalyse", "Accept-Profile": "finalyse",
                     "Prefer": "resolution=merge-duplicates,return=minimal"})
        urllib.request.urlopen(req, timeout=90)

    _post("instruments", [{"symbol": symbol, "isin": isin,
                           "label": (meta or {}).get("nom"), "asset_class": "UC",
                           "universe": ["quantalys_uc"]}])
    rows = [{"symbol": symbol, "date": d.strftime("%Y-%m-%d"),
             "adjusted_close": float(v)} for d, v in base100.items()]
    for i in range(0, len(rows), chunk):
        _post("prices", rows[i:i + chunk])
    return {"symbol": symbol, "rows": len(rows)}


def push_all_supabase():
    """Pousse toutes les UC du cache local vers Supabase. Renvoie le récap."""
    m = _load_manifest()
    out = []
    for isin, entry in m.items():
        res = push_supabase(isin, load_uc_series(isin), entry)
        out.append(res)
    return out
