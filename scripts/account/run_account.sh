#!/bin/bash
# shellcheck disable=SC1090
# run_account.sh <account> — универсальный запускатор одного аккаунта.
export PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Аккаунт = файл accounts/<name>.env (PERSONA/PROFILE, SUBJECTS, CDP_PORT, PROFILE[, READY-флаг]).
# БД по умолчанию: data/<name>.db. Новый акк = новый .env файл, ноль правок кода.
set -u
ACC="${1:?usage: run_account.sh <account>}"
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENVF="$BASE/accounts/$ACC.env"
[ -f "$ENVF" ] || { echo "нет аккаунта: $ENVF" >&2; exit 1; }
set -a
. "$ENVF"
set +a
export PROFI_DB="${PROFI_DB:-$BASE/data/$ACC.db}"
export PROFI_CHROME_PATH="${PROFI_CHROME_PATH:-$BASE/scripts/browser/chrome-vps.sh}"
export PROFI_RHYTHM_TAG="$ACC"
cd "$BASE" || exit 1

# Важно: не подменяем отсутствующий PROFI_PERSONA именем аккаунта. Account alias
# (например profi3) не является business persona; config.py сам выведет persona
# из PROFI_PROFILE либо legacy/default-настроек.

# браузер (если порт мёртв) — generic лаунчер
curl -s -m 3 "http://127.0.0.1:${PROFI_CDP_PORT}/json/version" >/dev/null 2>&1 || \
  setsid "$BASE/scripts/browser/launch_account_browser.sh" "$ACC" </dev/null >> "logs/browser-$ACC.log" 2>&1 &

# Воркер — только если акк залогинен (флаг accounts/<acc>.ready).
# pgrep остаётся дешёвой оптимизацией, но НЕ является mutex: два параллельных
# run_account.sh могут одновременно увидеть «процесса нет». Поэтому сам
# долгоживущий worker запускается под flock, который держится весь lifetime.
# Перед НОВЫМ стартом обязательно проходит read-only code + account-config
# preflight. Уже живой worker не трогаем на каждом rhythm-check.
WPAT="profi.main --rhythm-tag $ACC\$"
WLOCK="$BASE/data/$ACC.worker.lock"
if [ -f "accounts/$ACC.ready" ] && ! pgrep -f "$WPAT" >/dev/null 2>&1; then
  if ! bash "$BASE/scripts/account/preflight_worker.sh" "$ACC"; then
    echo "worker $ACC не запущен: code/account preflight failed" >&2
    exit 1
  fi
  setsid flock -n "$WLOCK" \
    env PROFI_RHYTHM_TAG="$ACC" PROFI_DB="$PROFI_DB" \
    PROFI_CHROME_PROFILE="$PROFI_CHROME_PROFILE" PROFI_CDP_PORT="$PROFI_CDP_PORT" \
    ${PROFI_SUBJECTS:+PROFI_SUBJECTS="$PROFI_SUBJECTS"} \
    xvfb-run -a uv run python -m profi.main --rhythm-tag "$ACC" >> "logs/worker-$ACC.log" 2>&1 &
fi
