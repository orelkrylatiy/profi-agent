#!/bin/bash
# rhythm_keeper.sh — человеческий ритм онлайн-присутствия.
# Правила (приказ владельца 2026-09-01):
#  - гарантированно онлайн с 18:00 МСК (пик) — пауз не ставить
#  - в остальное время (глубокая ночь/утро МСК) — иногда пауза на 60–120 мин
#  - не чаще 2 пауз/сутки; пауза НЕ в окне 15:00–24:00 МСК (запас до пика)
#  - отклики/ответы важнее маскировки: паузы только когда всё спокойно
# Вызов: system cron каждые 15 мин. Идемпотентен.
set -u
MSK_H=$(TZ=Europe/Moscow date +%H)
STATE=/root/profi-agent/data/rhythm_state.json
TODAY=$(date +%F)
PAUSED_UNTIL=0
PAUSES_TODAY=0
LAST_DAY=""
[ -f "$STATE" ] && eval "$(jq -r '"PAUSED_UNTIL=\(.paused_until // 0) PAUSES_TODAY=\(.pauses_today // 0) LAST_DAY=\"\(.day // \"\")\""' "$STATE" 2>/dev/null)"
[ "$LAST_DAY" != "$TODAY" ] && PAUSES_TODAY=0
NOW=$(date +%s)

stop_all() {
  pkill -f "user-data-dir=/root/browser-profiles/profi2" 2>/dev/null
  pkill -f "PROFI_PERSONA=lang" 2>/dev/null
  pkill -f "user-data-dir=/root/browser-profiles/profi " 2>/dev/null
  pkill -f "chrome-vps.sh" 2>/dev/null
  # воркеры гасим по отличимым env: они запущены через обёртки run_info.sh/run_lang.sh
  pkill -f "PROFI_RHYTHM_TAG=info" 2>/dev/null
  pkill -f "PROFI_RHYTHM_TAG=lang" 2>/dev/null
}
start_all() {
  /root/profi-agent/scripts/run_info.sh
  /root/profi-agent/scripts/run_lang.sh
}

if [ "$NOW" -lt "$PAUSED_UNTIL" ]; then
  stop_all
  exit 0
fi

# вне паузы: гарантируем, что всё живо (если было погашено паузой — поднимаем)
if [ "$PAUSED_UNTIL" -gt 0 ]; then
  start_all
  PAUSED_UNTIL=0
fi

# решение о новой паузе: часы 01–14 МСК, вероятность ~8% на проверку (раз в 15 мин),
# в среднем одна пауза раз в ~3 часа окна → максимум 2
if [ "$MSK_H" -ge 1 ] && [ "$MSK_H" -lt 14 ] && [ "$PAUSES_TODAY" -lt 2 ]; then
  if [ $((RANDOM % 100)) -lt 8 ]; then
    DUR=$((60 + RANDOM % 61))           # 60–120 мин
    PAUSED_UNTIL=$((NOW + DUR * 60))
    PAUSES_TODAY=$((PAUSES_TODAY + 1))
    stop_all
    echo "$(date '+%F %T') пауза ${DUR}м (пауза №$PAUSES_TODAY за день)" >> /root/profi-agent/logs/rhythm.log
  fi
fi

jq -n --arg d "$TODAY" --argjson p "$PAUSED_UNTIL" --argjson n "$PAUSES_TODAY" \
  '{day:$d, paused_until:$p, pauses_today:$n}' > "$STATE"
