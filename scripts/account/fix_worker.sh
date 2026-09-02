#!/bin/bash
# shellcheck disable=SC1090
# fix_worker.sh <account> — перезапуск воркера аккаунта (убить зависший, поднять заново).
# Свой cmdline не содержит "PROFI_RHYTHM_TAG=<acc>", так что pkill себя не убьёт.
set -u
ACC="${1:?usage: fix_worker.sh <account>}"
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
pkill -f "PROFI_RHYTHM_TAG=$ACC" 2>/dev/null; sleep 1
cd "$BASE" || exit 1
set -a; . "$BASE/accounts/$ACC.env"; set +a
setsid env PROFI_RHYTHM_TAG="$ACC" PROFI_PERSONA="$PROFI_PERSONA" \
  PROFI_DB="${PROFI_DB:-$BASE/data/$ACC.db}" \
  PROFI_CHROME_PROFILE="$PROFI_CHROME_PROFILE" PROFI_CDP_PORT="$PROFI_CDP_PORT" \
  PROFI_CHROME_PATH="${PROFI_CHROME_PATH:-$BASE/scripts/browser/chrome-vps.sh}" \
  ${PROFI_SUBJECTS:+PROFI_SUBJECTS="$PROFI_SUBJECTS"} \
  xvfb-run -a uv run python -m profi.main >> "logs/worker-$ACC.log" 2>&1 &
sleep 8
echo "живых воркеров $ACC: $(pgrep -fc "PROFI_RHYTHM_TAG=$ACC")"
tail -3 "logs/worker-$ACC.log"
