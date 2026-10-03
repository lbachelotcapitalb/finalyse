#!/usr/bin/env bash
# Cron quotidien : mail à Léo si nouvelles demandes de référencement (bWealthy).
# Secrets lus sur place, jamais versionnés : Supabase depuis ~/finalyse/.env,
# Resend depuis l'env Finengy (même canal que le décryptage LinkedIn).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
RESEND_API_KEY="$(grep -E '^RESEND_API_KEY=' /opt/finengy/AGENT_VPS/.env | cut -d= -f2- | tr -d "\"'")"
export RESEND_API_KEY
: "${RESEND_API_KEY:?RESEND_API_KEY introuvable}"
exec .venv/bin/python scripts/notify_demandes.py
