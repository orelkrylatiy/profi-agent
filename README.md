# Контур A — воркер откликов Профи.ру

**АВТОРЕЖИМ (с 2026-08-31):** лента → фильтры → LLM-триаж и кастомный текст
→ автоматическая отправка откликов с гейтами (лимит 3/день, потолок 500 ₽,
позиция ≤ 20, рабочие часы 8–23). Ручная отправка тоже доступна (`respond`).
Спека: vault `01 Projects/Репетиторство/Спека — Контур A (воркер откликов).md`,
рабочая копия: `docs/SPEC.md`, правила: `RULES.md`.

## Текущее состояние: M7 — автономный контур

- воркер `src/profi/main.py` (nohup, цикл 90–120 с, запуск `uv run python -m profi`)
  — лента/фильтры/кандидаты/детали;
- диспетчер launchd `com.profi.autopilot` (каждые 120 с) → `main.py autopilot`
  — жёсткие гейты → LLM (GLM-5.3) триаж+текст → отправка → `logs/autopilot.log`;
- LLM-слой `src/profi/llm/` — мульти-провайдерный (glm / openai / anthropic-протокол),
  настройка в `.env`.

## Настройка

```bash
cd ~/profi
uv sync
cp .env.example .env   # вписать ключ (сейчас: Z.AI coding plan, GLM-5.3)
uv run python -m profi llm-check   # проверка: модель должна ответить
```

Chrome — системный, отдельный профиль `data/chrome-profiles/main`,
CDD-порт **9333**, запуск `scripts/browser/start-chrome.sh` (идемпотентен).

## Команды

```bash
uv run python -m profi                  # рабочий цикл воркера (90–120 с)
uv run python -m profi --once           # один цикл
uv run python -m profi autopilot        # один проход автопилота вручную
uv run python -m profi llm-check        # живая проверка LLM
uv run python -m profi candidates       # список кандидатов со статусами
uv run python -m profi stats            # статистика откликов (v_responses)
uv run python -m profi fetch-details <id>   # дозагрузка карточки заказа
uv run python -m profi respond <id> --rate N --text '...' [--send]
uv run python -m profi note <id> --text '...'   # описание/резон в статистику
uv run python -m profi sent|skip <id>   # ручной гейт
uv run pytest                           # тесты чистой логики
```

## Где что лежит

- `src/profi/` — пакет: `main` (CLI/оркестрация), `browser` (Chrome/CDP),
  `integration` (лента/карточки/отклики/чаты), `llm`, `storage` (SQLite),
  `models`, `utils`, `config`;
- `data/profi.db` — SQLite: `feed_seen`, `candidates`, вьюшка `v_responses`;
  `data/browser-profiles/` — профили Chrome (сессии);
- `logs/worker.log` — воркер; `logs/autopilot.log` — решения автопилота;
  `logs/launchd.log` — диспетчер; `logs/respond/` — скриншоты/JSON отправок;
- `docs/` — SPEC (рабочая спека), JOURNAL (журнал экспериментов), BACKLOG;
- `scripts/` — `rhythm_keeper.sh`/`autopilot_cron.sh` (точки входа кронов),
  `account/` (воркеры), `browser/` (Chrome), `diag/` (пробники).

Настройки: `src/profi/config.py` (порт, интервалы, фильтры, лимиты, RATE).
