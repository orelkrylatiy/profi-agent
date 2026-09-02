#!/bin/bash
# Диспетчер чат-автоответов (launchd com.profi.chats, каждые 4 мин).
# Дешёвая цепочка: chats_unread.py (read-only, 0 токенов) → есть непрочитанные
# → chat-auto (лимиты вшиты: ≤2 ответа за запуск, ≥30 мин между ответами
# на диалог, autopilot.lock сериализует с платными отправками).
# Chrome должен быть жив; если CDP мёртв — пробник вернёт ok:false и мы выйдем.
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
LOG=logs/chats_cron.log
echo "[$(date '+%F %T')] chats-cron: запуск" >> "$LOG"

OUT="$(uv run python scripts/diag/chats_unread.py 2>>"$LOG")"

# Самолечение: Chrome мёртв — поднимаем (start-chrome.sh идемпотентен)
# и перепроверяем один раз, иначе после перезагрузки Mac чаты ждали бы вечно.
if printf '%s' "$OUT" | grep -q '"ok": false'; then
  echo "[$(date '+%F %T')] probe: CDP мёртв → start-chrome.sh" >> "$LOG"
  bash scripts/browser/start-chrome.sh >> "$LOG" 2>&1 || true
  sleep 10
  OUT="$(uv run python scripts/diag/chats_unread.py 2>>"$LOG")"
fi
echo "[$(date '+%F %T')] probe: $OUT" >> "$LOG"

# Бейдж «Чаты» в навигации показывает глобальный счётчик (не диалоги),
# поэтому реагируем только на изменение списка диалогов + любые непрочитанные.
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
