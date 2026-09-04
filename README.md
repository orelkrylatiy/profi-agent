# Контур A — воркер откликов Профи.ру (+ Контур B light: автоответы в чатах)

**АВТОРЕЖИМ (с 2026-08-31):** лента → фильтры → LLM-триаж и кастомный текст
→ автоматическая отправка откликов с гейтами (потолок цены отклика, позиция ≤ 20,
рабочие часы 8–23). Ручная отправка тоже доступна (`respond`).
**Чаты (с 2026-09-02):** воркер сам отвечает клиентам через LLM — каждый
N-й цикл (`PROFI_CHAT_EVERY`, дефолт 3 ≈ раз в 4.5–6 мин). Гейты:
`autopilot.lock` (не пересекается с платной отправкой), ≤2 ответов за
запуск, ≥30 мин на диалог, needs_human → владельцу, анти-инъекция
(в тексте для клиента запрещены ссылки/телефоны).
Спека: vault `01 Projects/Репетиторство/Спека — Контур A (воркер откликов).md`,
рабочая копия: `docs/SPEC.md`, правила: `RULES.md`.

## Текущее состояние: M7 — автономный контур

- воркер `src/profi/main.py` (nohup, цикл 45–60 с, запуск `uv run python -m profi`)
  — лента/фильтры/кандидаты/детали **+ чат-чек каждый N-й цикл**;
- диспетчер launchd `com.profi.autopilot` (каждые 120 с) → `main.py autopilot`
  — жёсткие гейты → LLM (GLM-5.3) триаж+текст → отправка → `logs/autopilot.log`;
- диспетчер launchd `com.profi.chats` (каждые 240 с) → `chats_unread.py`
  (дешёвый пробник, 0 токенов) → `chat-auto` — **запасной** путь чатов,
  когда воркер не запущен;
- LLM-слой `src/profi/llm/` — мульти-провайдерный (glm / openai / anthropic-протокол),
  настройка в `.env`;
- `profiles/` — бизнес-профили офферов: предметы, профильные stop-слова,
  persona и библиотека fallback-текстов отдельно от Chrome/DB конкретного аккаунта.

## Business profiles

Один profile = один оффер/тип преподавателя, а не обязательно один предмет.
Сейчас:

```text
profiles/info.toml        информатика / программирование
profiles/languages.toml   английский + испанский одним языковым профилем
```

Рекомендуется выбирать профиль в `accounts/<account>.env`:

```env
PROFI_PROFILE=info
```

или:

```env
PROFI_PROFILE=languages
```

`PROFI_PERSONA`, `PROFI_SUBJECTS` и `PROFI_STOP_PATTERNS` сохранены как
обратносуместимые override'ы: существующие account env можно мигрировать постепенно.
Legacy `PROFI_PERSONA=info` автоматически соответствует `profile=info`, а
`PROFI_PERSONA=lang` — `profile=languages`.

Fallback-шаблоны уже лежат внутри профилей, но **пока не отправляются автоматически**
при недоступной LLM. Их подключение планируется вместе с fast-path, чтобы изменение
поведения отправки было отдельным, контролируемым шагом.

Подробно: `profiles/README.md`.

## Настройка

```bash
cd ~/profi
uv sync
cp .env.example .env   # вписать ключ (сейчас: Z.AI coding plan, GLM-5.3)
uv run python -m profi llm-check   # проверка: модель должна ответить
uv tool install pre-commit && pre-commit install   # хуки: ruff + shellcheck (опционально)
```

Chrome — системный, отдельный профиль `data/chrome-profiles/main`,
CDP-порт **9333**, запуск `scripts/browser/start-chrome.sh` (идемпотентен).

## Команды

```bash
uv run python -m profi                  # рабочий цикл воркера (45–60 с)
uv run python -m profi --once           # один цикл
uv run python -m profi autopilot        # один проход автопилота вручную
uv run python -m profi llm-check        # живая проверка LLM
uv run python -m profi candidates       # список кандидатов со статусами
uv run python -m profi stats            # статистика откликов (v_responses)
uv run python -m profi fetch-details <id>   # дозагрузка карточки заказа
uv run python -m profi respond <id> --rate N --text '...' [--send]
uv run python -m profi note <id> --text '...'   # описание/резон в статистику
uv run python -m profi sent|skip <id>   # ручной гейт
uv run python -m profi chats            # список чатов (read-only)
uv run python -m profi chat-auto        # ответить в чатах сейчас (вне цикла)
uv run pytest                           # тесты чистой логики
```

## Где что лежит

- `src/profi/` — общий engine: `main` (CLI/оркестрация), `browser` (Chrome/CDP),
  `integration` (лента/карточки/отклики/чаты), `llm`, `storage` (SQLite),
  `models`, `utils`, `config`, `profiles` (TOML loader);
- `profiles/` — бизнес-конфигурация оффера: предметы, stop-слова, persona,
  fallback templates;
- `personas/` — LLM-идентичность преподавателя;
- `accounts/*.env` — конкретный экземпляр аккаунта: профиль, Chrome/CDP, DB, тариф;
- `data/profi.db` — SQLite: `feed_seen`, `candidates`, `chat_log`,
  вьюшка `v_responses`; `data/browser-profiles/` — профили Chrome (сессии);
- `logs/worker.log` — воркер; `logs/autopilot.log` — решения автопилота;
  `logs/chats_cron.log` — чат-дозор; `logs/launchd.log` — диспетчер;
  `logs/respond/` и `logs/chats/` — скриншоты отправок;
- `docs/` — SPEC (рабочая спека), JOURNAL (журнал экспериментов), BACKLOG;
- `scripts/` — `rhythm_keeper.sh`/`autopilot_cron.sh` (точки входа кронов),
  `account/` (воркеры), `browser/` (Chrome), `diag/` (пробники).

Приоритет настройки бизнес-части: account env override → `.env` override →
`profiles/<name>.toml` → дефолт engine. Runtime-настройки браузера и БД остаются
в account env / `src/profi/config.py`.
