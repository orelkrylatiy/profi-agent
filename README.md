# Контур A — воркер откликов Профи.ру

**АВТОРЕЖИМ (с 2026-08-31):** лента → фильтры → LLM-триаж и кастомный текст
→ автоматическая отправка откликов с гейтами (лимит 3/день, потолок 500 ₽,
позиция ≤ 20, рабочие часы 8–23). Ручная отправка тоже доступна (`respond`).
Спека: vault `01 Projects/Репетиторство/Спека — Контур A (воркер откликов).md`,
рабочая копия: `docs/SPEC.md`, правила: `RULES.md`.

## Текущее состояние: M7 — автономный контур

- воркер `main.py` (nohup, цикл 90–120 с) — лента/фильтры/кандидаты/детали;
- диспетчер launchd `com.profi.autopilot` (каждые 120 с) → `main.py autopilot`
  — жёсткие гейты → LLM (GLM-5.3) триаж+текст → отправка → `logs/autopilot.log`;
- LLM-слой `llm.py` — мульти-провайдерный (glm / openai / anthropic-протокол),
  настройка в `.env`.

## Настройка

```bash
cd ~/profi
uv sync
cp .env.example .env   # вписать ключ (сейчас: Z.AI coding plan, GLM-5.3)
uv run python main.py llm-check   # проверка: модель должна ответить
```

Chrome — системный, отдельный профиль `data/chrome-profiles/main`,
CDD-порт **9333**, запуск `scripts/start-chrome.sh` (идемпотентен).

## Команды

```bash
uv run python main.py                  # рабочий цикл воркера (90–120 с)
uv run python main.py --once           # один цикл
uv run python main.py autopilot        # один проход автопилота вручную
uv run python main.py llm-check        # живая проверка LLM
uv run python main.py candidates       # список кандидатов со статусами
uv run python main.py stats            # статистика откликов (v_responses)
uv run python main.py fetch-details <id>   # дозагрузка карточки заказа
uv run python main.py respond <id> --rate N --text '...' [--send]
uv run python main.py note <id> --text '...'   # описание/резон в статистику
uv run python main.py sent|skip <id>   # ручной гейт
```

## Где что лежит

- `data/profi.db` — SQLite: `feed_seen`, `candidates`, вьюшка `v_responses`;
- `logs/worker.log` — воркер; `logs/autopilot.log` — решения автопилота;
  `logs/launchd.log` — диспетчер; `logs/respond/` — скриншоты/JSON отправок;
- `docs/` — SPEC (рабочая спека), JOURNAL (журнал экспериментов), BACKLOG.

Настройки: `config.py` (порт, интервалы, фильтры, лимиты, RATE).
