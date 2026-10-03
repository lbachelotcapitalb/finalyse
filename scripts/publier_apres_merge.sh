#!/usr/bin/env bash
# À lancer UNE FOIS bwealthy#61 mergée et déployée (03/10/2026) :
#   1. publie le run générique avec les recos 1·2·4 (1/N recommandable) ;
#   2. réactive le dernier calcul de chaque contrat (mis en attente : l'écran
#      d'avant #61 titrait la reco 1/N « Drawdown minimal »).
# Réversible : finalyse.portfolios garde les anciennes lignes (is_current=false).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
.venv/bin/python push_portfolios.py "${1:-result_v2.json}"
.venv/bin/python - <<'PY'
import json, os, urllib.request
base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
k = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": k, "Authorization": f"Bearer {k}", "Content-Type": "application/json",
     "Accept-Profile": "finalyse", "Content-Profile": "finalyse"}
def req(m, p, b=None):
    r = urllib.request.urlopen(urllib.request.Request(base + p, method=m, headers=H,
                               data=json.dumps(b).encode() if b is not None else None))
    t = r.read().decode(); return json.loads(t) if t else None
rows = req("GET", "contrat_portfolios?select=id,contrat_code,computed_at&order=computed_at.desc")
dernier = {}
for r in rows:
    dernier.setdefault(r["contrat_code"], r["id"])
for code, i in sorted(dernier.items()):
    req("PATCH", f"contrat_portfolios?contrat_code=eq.{code}&is_current=is.true", {"is_current": False})
    req("PATCH", f"contrat_portfolios?id=eq.{i}", {"is_current": True})
    print(f"✓ {code} : calcul {i} servi")
PY
