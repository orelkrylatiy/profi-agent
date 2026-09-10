#!/bin/bash
# shellcheck disable=SC1090
# fix_worker.sh <account> — безопасный перезапуск воркера аккаунта.
# Сначала read-only preflight нового кода + реального account env, только потом
# убиваем старый worker.
set -u
ACC="${1:?usage: fix_worker.sh <account>}"
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
cd "$BASE" || exit 1

if ! bash "$BASE/scripts/account/preflight_worker.sh" "$ACC"; then
  echo "worker $ACC НЕ перезапущен: preflight нового кода/account env не прошёл" >&2
  exit 1
fi

set -a
. "$BASE/accounts/$ACC.env"
set +a

# Паттерн матчит argv воркера (--rhythm-tag); свой cmdline его не содержит.
pkill -f "profi.main --rhythm-tag $ACC\$" 2>/dev/null || true
sleep 1

WLOCK="$BASE/data/$ACC.worker.lock"
# После SIGTERM старый worker может несколько секунд закрывать Playwright/SQLite.
# На forced restart ждём освобождения singleton-lock, а не теряем единственную
# попытку старта из-за короткого overlap окна.
setsid flock -w 15 "$WLOCK" \
  env PROFI_RHYTHM_TAG="$ACC" PROFI_PERSONA="$PROFI_PERSONA" \
  PROFI_DB="${PROFI_DB:-$BASE/data/$ACC.db}" \
  PROFI_CHROME_PROFILE="$PROFI_CHROME_PROFILE" PROFI_CDP_PORT="$PROFI_CDP_PORT" \
  PROFI_CHROME_PATH="${PROFI_CHROME_PATH:-$BASE/scripts/browser/chrome-vps.sh}" \
  ${PROFI_SUBJECTS:+PROFI_SUBJECTS="$PROFI_SUBJECTS"} \
  xvfb-run -a uv run python -m profi.main --rhythm-tag "$ACC" >> "logs/worker-$ACC.log" 2>&1 &
sleep 8
COUNT="$(pgrep -fc "profi.main --rhythm-tag $ACC\$")"
echo "живых воркеров $ACC: $COUNT"
tail -3 "logs/worker-$ACC.log"

if [[ "$COUNT" -lt 1 ]]; then
  echo "worker $ACC не поднялся после restart" >&2
  exit 1
fi
