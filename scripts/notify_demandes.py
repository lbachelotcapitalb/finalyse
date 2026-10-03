#!/usr/bin/env python3
"""Mail à Léo : nouvelles demandes de référencement de contrat (bWealthy).

Lit `finalyse.demandes_referencement` (statut 'ouverte', `notifie_at` nul), envoie
UN mail récapitulatif via Resend, puis pose `notifie_at` sur les lignes envoyées.
Rien de nouveau → aucun mail (le silence est le cas normal).

Ordre voulu : on marque APRÈS un envoi réussi. Un échec d'envoi laisse les lignes
non marquées → elles repartent au prochain passage (doublon possible, perte jamais).

Env : SUPABASE_URL, SUPABASE_SERVICE_KEY (~/finalyse/.env) ; RESEND_API_KEY
(+ RESEND_FROM facultatif) ; DEMANDES_EMAIL_TO (défaut lbachelot@capitalb.fr).
--dry-run : affiche le mail sans l'envoyer ni marquer.
--test : préfixe le sujet de « 🧪 TEST » (preuve de bout en bout, jamais confondue avec une vraie alerte).
"""
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TO = os.environ.get("DEMANDES_EMAIL_TO", "lbachelot@capitalb.fr")
FROM = os.environ.get("RESEND_FROM", "Finengy Advisory <cabinet-finengy@finengy.fr>")


def _sb(method, path, body=None, profile="finalyse", auth_api=False):
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    url = f"{base}/auth/v1/{path}" if auth_api else f"{base}/rest/v1/{path}"
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if not auth_api:
        h.update({"Accept-Profile": profile, "Content-Profile": profile, "Prefer": "return=minimal"})
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers=h)
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    return json.loads(raw) if raw else None


def _email_of(uid):
    try:
        return (_sb("GET", f"admin/users/{uid}", auth_api=True) or {}).get("email") or uid
    except Exception:  # noqa: BLE001 — un compte supprimé ne bloque pas l'alerte
        return uid


def main():
    dry = "--dry-run" in sys.argv
    rows = _sb("GET", "demandes_referencement?select=*&statut=eq.ouverte&notifie_at=is.null"
                      "&order=created_at") or []
    if not rows:
        print("aucune nouvelle demande")
        return
    lignes = []
    for r in rows:
        quoi = r["libelle_contrat"] + (f" — {r['assureur']}" if r.get("assureur") else "")
        cas = "menu à charger" if r.get("contrat_code") else "contrat absent du catalogue"
        lignes.append((r["created_at"][:16].replace("T", " "), quoi, cas, _email_of(r["demandeur"]),
                       r.get("message") or ""))
    sujet = (("🧪 TEST · " if "--test" in sys.argv else "")
             + f"bWealthy · {len(rows)} demande(s) de référencement de contrat")
    tr = "".join(
        f"<tr><td style='padding:6px 10px;border-top:1px solid #e5e7eb'>{html.escape(d)}</td>"
        f"<td style='padding:6px 10px;border-top:1px solid #e5e7eb'><b>{html.escape(q)}</b><br>"
        f"<span style='color:#6b7280'>{html.escape(c)}</span></td>"
        f"<td style='padding:6px 10px;border-top:1px solid #e5e7eb'>{html.escape(u)}"
        f"{'<br><i>' + html.escape(msg) + '</i>' if msg else ''}</td></tr>"
        for d, q, c, u, msg in lignes)
    corps = (
        "<div style='font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;font-size:14px;color:#111827'>"
        f"<p>{len(rows)} nouvelle(s) demande(s) depuis le dernier envoi.</p>"
        "<table style='border-collapse:collapse;width:100%'>"
        "<tr style='text-align:left;color:#6b7280'><th style='padding:6px 10px'>Reçue (UTC)</th>"
        "<th style='padding:6px 10px'>Contrat</th><th style='padding:6px 10px'>Demandeur</th></tr>"
        f"{tr}</table>"
        "<p style='color:#6b7280'>Pour servir un contrat : charger son menu officiel dans "
        "<code>finalyse.contrat_univers</code> (source obligatoire), puis "
        "<code>run_contrats.py --contrat &lt;code&gt;</code>. Clore la demande : "
        "<code>statut = 'referencee'</code>.</p></div>")
    if dry:
        print(sujet); print(corps)
        return
    req = urllib.request.Request(
        "https://api.resend.com/emails", method="POST",
        data=json.dumps({"from": FROM, "to": [TO], "subject": sujet, "html": corps}).encode(),
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
                 "Content-Type": "application/json", "User-Agent": "finalyse/1.0"})
    rid = json.loads(urllib.request.urlopen(req, timeout=30).read().decode()).get("id")
    ids = ",".join(str(r["id"]) for r in rows)
    _sb("PATCH", f"demandes_referencement?id=in.({urllib.parse.quote(ids)})",
        {"notifie_at": datetime.now(timezone.utc).isoformat()})
    print(f"✓ mail envoyé à {TO} (resend {rid}) — {len(rows)} demande(s) marquée(s)")


if __name__ == "__main__":
    main()
