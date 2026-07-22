"""Pousse result_portfolios.json vers Supabase (table finalyse.portfolios).

C'est le mécanisme « réactualiser sans redéployer le front bWealthy » : après un
run `run_portfolios.py`, lancer ce script → le front lit la nouvelle version.
Marque l'ancien courant à false puis insère la nouvelle ligne is_current=true
(l'index unique partiel garantit un seul courant).

Env : SUPABASE_URL + SUPABASE_SERVICE_KEY (via bw-get / ask-secret, jamais en
clair). Schéma exposé via les en-têtes Content/Accept-Profile: finalyse.
Usage : SUPABASE_URL=… SUPABASE_SERVICE_KEY=… .venv/bin/python push_portfolios.py [fichier.json]
"""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(__file__)


def _req(base, key, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{base}/rest/v1/{path}", data=data, method=method,
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Content-Profile": "finalyse", "Accept-Profile": "finalyse",
                 "Prefer": "return=minimal"})
    return urllib.request.urlopen(req, timeout=60)


def main():
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not base or not key:
        sys.exit("SUPABASE_URL / SUPABASE_SERVICE_KEY absents de l'env.")
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "result_portfolios.json")
    payload = json.load(open(src, encoding="utf-8"))

    # 1) déprécier l'ancien courant, 2) insérer le nouveau courant
    _req(base, key, "PATCH", "portfolios?is_current=eq.true", {"is_current": False})
    _req(base, key, "POST", "portfolios", {"payload": payload, "is_current": True})
    print(f"✓ portefeuilles poussés (courant) depuis {os.path.basename(src)} "
          f"— {len(payload.get('enveloppes', {}))} enveloppes.")


if __name__ == "__main__":
    main()
