#!/bin/bash
# Legacy-диспетчер чат-автоответов (launchd com.profi.chats, каждые 4 мин).
# Основной production-path — chat check внутри worker; этот скрипт оставлен для
# rollback/старого Mac setup. chats_unread.py read-only и не тратит LLM-токены.
# chat-auto сам ограничивает число ответов и сериализуется через autopilot.lock.
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
LOG=logs/chats_cron.log
echo "[$(date '+%F %T')] chats-cron: запуск" >> "$LOG"

OUT="$(uv run python scripts/diag/chats_unread.py 2>>"$LOG")"

# Самолечение только для явного dead-CDP. Другие ok:false (например,
# «нерабочие часы») НЕ означают, что Chrome надо запускать: ночью автономные
# контуры по RULES вообще не должны трогать браузер.
if printf '%s' "$OUT" | grep -q '"error": "cdp_dead"'; then
  echo "[$(date '+%F %T')] probe: CDP мёртв → start-chrome.sh" >> "$LOG"
  bash scripts/browser/start-chrome.sh >> "$LOG" 2>&1 || true
  sleep 10
  OUT="$(uv run python scripts/diag/chats_unread.py 2>>"$LOG")"
fi
echo "[$(date '+%F %T')] probe: $OUT" >> "$LOG"

# Бейдж «Чаты» в навигации показывает глобальный счётчик (не диалоги),
# поэтому legacy trigger реагирует на изменение списка + непрочитанные.
# Надёжный retry по message-id/fingerprint ещё не реализован — см. BACKLOG.md.
READ="$(printf '%s' "$OUT" | uv run python -c '
import json, sys
try:
    d = json.loads(sys.stdin.read())
    if not d.get("ok"):
        print("-1 0")
    else:
        print(int(d.get("unread") or 0), 1 if d.get("changed") else 0)
except Exception:
    print("-1 0")')"
UNREAD="${READ%% *}"
CHANGED="${READ##* }"

if [ "$UNREAD" -le 0 ] || [ "$CHANGED" != "1" ]; then
  exit 0
fi

echo "[$(date '+%F %T')] chats-cron: непрочитанных $UNREAD → chat-auto" >> "$LOG"
exec uv run python -m profi chat-auto >> "$LOG" 2>&1
