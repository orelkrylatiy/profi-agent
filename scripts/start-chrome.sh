#!/usr/bin/env bash
#
# Запуск отдельного Chrome с CDP для воркера profi (Контур A).
#
# Использование:
#   ./scripts/start-chrome.sh [profile] [port]
#     profile — имя профиля в data/chrome-profiles/ (по умолчанию main)
#     port    — CDP-порт (по умолчанию 9333)
#
# Подключение из кода (Playwright / любой CDP-клиент):
#   chromium.connect_over_cdp("http://127.0.0.1:9333")
#
# Флаги:
#   --remote-debugging-port  — поднимает CDP-сервер на указанном порту
#   --remote-allow-origins=* — разрешает WebSocket-подключения к CDP
#                              из любых клиентов (иначе Chrome 111+ отклоняет
#                              подключения не из DevTools)
#   --user-data-dir          — изолированный профиль (Chrome 136+ отказывается
#                              открывать CDP на дефолтном профиле)
#   --no-first-run --no-default-browser-check — без лишних попапов на новом профиле

set -euo pipefail

PROFILE="${1:-main}"
PORT="${2:-9333}"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILES_DIR="$HOME/profi/data/chrome-profiles"
PROFILE_DIR="$PROFILES_DIR/$PROFILE"
START_URL="https://profi.ru/backoffice/n.php"

if [[ ! -x "$CHROME" ]]; then
  echo "Ошибка: Chrome не найден: $CHROME" >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"

check_cdp() {
  curl -s --noproxy '*' --max-time 2 "http://127.0.0.1:${PORT}/json/version" || true
}

# Уже запущен этот профиль?
if check_cdp | grep -q "Browser"; then
  echo "Chrome уже запущен (профиль: ${PROFILE}, порт: ${PORT})"
  check_cdp
  exit 0
fi

nohup "$CHROME" \
  --user-data-dir="$PROFILE_DIR" \
  --remote-debugging-port="$PORT" \
  --remote-allow-origins='*' \
  --no-first-run \
  --no-default-browser-check \
  "$START_URL" > /dev/null 2>&1 &

# Ждём, пока CDP-сервер поднимется (до 15 сек)
for _ in $(seq 1 30); do
  if check_cdp | grep -q "Browser"; then
    echo "CDP готов: http://127.0.0.1:${PORT} (профиль: ${PROFILE})"
    check_cdp
    exit 0
  fi
  sleep 0.5
done

echo "Ошибка: CDP не поднялся на порту ${PORT} за 15 сек" >&2
exit 1
