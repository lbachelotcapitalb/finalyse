#!/usr/bin/env bash
# Cron quotidien : sync INCRÉMENTAL des cours EODHD → Supabase (pas --full :
# n'ajoute que les nouvelles clôtures depuis la dernière date en base).
#
# Secrets requis dans l'environnement (JAMAIS commités) :
#   EODHD_API_TOKEN, SUPABASE_URL, SUPABASE_SERVICE_KEY
# Fournis-les via un EnvironmentFile systemd root-only, l'env du cron, ou un
# bw-get imbriqué sur une machine où Bitwarden est déverrouillé.
#
# Optionnel : FINALYSE_PYTHON (chemin du python du venv), sinon python3.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${EODHD_API_TOKEN:?manquant}"; : "${SUPABASE_URL:?manquant}"; : "${SUPABASE_SERVICE_KEY:?manquant}"
PY="${FINALYSE_PYTHON:-python3}"
export PYTHONPATH="$(pwd)"
"$PY" -m finalyse.sync_supabase --universe all
