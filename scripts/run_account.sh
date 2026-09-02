#!/bin/bash
# run_account.sh <account> — универсальный запускатор одного аккаунта.
export PATH=/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Аккаунт = файл accounts/<name>.env (PERSONA, SUBJECTS, CDP_PORT, PROFILE[, READY-флаг]).
# БД по умолчанию: data/<name>.db. Новый акк = новый .env файл, ноль правок кода.
set -u
ACC="${1:?usage: run_account.sh <account>}"
BASE=/root/profi-agent
ENVF="$BASE/accounts/$ACC.env"
[ -f "$ENVF" ] || { echo "нет аккаунта: $ENVF" >&2; exit 1; }
set -a; . "$ENVF"; set +a
export PROFI_DB="${PROFI_DB:-$BASE/data/$ACC.db}"
export PROFI_CHROME_PATH="${PROFI_CHROME_PATH:-/root/profi-agent/scripts/chrome-vps.sh}"
export PROFI_RHYTHM_TAG="$ACC"
export PROFI_PERSONA="${PROFI_PERSONA:-$ACC}"
cd "$BASE" || exit 1

# браузер (если порт мёртв) — generic лаунчер
curl -s -m 3 "http://127.0.0.1:${PROFI_CDP_PORT}/json/version" >/dev/null 2>&1 || \
  setsid "$BASE/scripts/launch_account_browser.sh" "$ACC" </dev/null >> "logs/browser-$ACC.log" 2>&1 &

# воркер — только если акк залогинен (флаг accounts/<acc>.ready)
if [ -f "accounts/$ACC.ready" ]; then
  pgrep -f "PROFI_RHYTHM_TAG=$ACC" >/dev/null 2>&1 || \
    setsid env PROFI_RHYTHM_TAG="$ACC" PROFI_PERSONA="$PROFI_PERSONA" PROFI_DB="$PROFI_DB" \
      PROFI_CHROME_PROFILE="$PROFI_CHROME_PROFILE" PROFI_CDP_PORT="$PROFI_CDP_PORT" \
      ${PROFI_SUBJECTS:+PROFI_SUBJECTS="$PROFI_SUBJECTS"} \
      xvfb-run -a uv run python -m profi.main >> "logs/worker-$ACC.log" 2>&1 &
fi
