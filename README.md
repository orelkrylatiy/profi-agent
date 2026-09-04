# Контур A — воркер откликов Профи.ру (+ Контур B light: автоответы в чатах)

**Основной flow:** лента → hard-filter → открыть свежий заказ один раз → FullOrder →
полные гейты → LLM-триаж → отправить отклик **в той же вкладке**. Если LLM временно
недоступна, после детерминированных гейтов используется безопасный fallback из
`profiles/<profile>.toml`. После обработки вкладка заказа закрывается.

**Чаты:** воркер периодически отвечает клиентам через LLM. Для чатов fallback не
используется: при LLM cooldown они молчат. В тексте для клиента запрещены
ссылки/телефоны; `needs_human` передаёт диалог владельцу.

Спека: `docs/SPEC.md`, архитектура: `docs/ARCHITECTURE.md`, правила: `RULES.md`.

## Fast-path: как работает

По умолчанию `PROFI_FAST_PATH=1`.

```text
feed
  ↓
NEW + hard filters
  ↓
create candidate
  ↓
open order page
  ↓
extract FullOrder
  ↓
SQLite: details=ready + draft=generating   ← атомарный claim
  ↓
full gates: vacancy / price / position / existing bid
  ↓
LLM available?
  ├─ yes → semantic triage
  │          ├─ skip → terminal skipped
  │          └─ send → validate text
  └─ no / provider limit / bad JSON or bad text
             → validated profile fallback
  ↓
SQLite: not_sent → sending                 ← atomic send claim
  ↓
open response form ON THE SAME PAGE
  ↓
fill + payment gates + click send
  ↓
sent / unknown / failed / skipped          ← terminal
  ↓
close order page
```

### Что принципиально изменилось

- хороший свежий заказ больше не закрывается перед LLM и не открывается второй раз;
- `unknown` после необратимой попытки отправки terminal: автоматически повторять нельзя;
- `failed/skipped` fast-path тоже не ставятся в очередь на фоновый reopen;
- `open_candidate()` сохраняет только свой локальный immediate technical retry для direct URL;
- LLM cooldown больше не останавливает чтение ленты: fresh orders идут через fallback;
- SQLite остаётся журналом, статистикой и защитой от двойной отправки.

Rollback без отката кода:

```env
PROFI_FAST_PATH=0
```

Тогда worker снова только собирает details, а отдельный `autopilot` обрабатывает
`details=ready + draft=pending`. Это compatibility/rollback path, а не основной flow.

## Business profiles

Один profile = один оффер/тип преподавателя, не обязательно один предмет.

```text
profiles/info.toml        информатика / программирование
profiles/languages.toml   английский + испанский одним языковым профилем
```

Аккаунт выбирает профиль:

```env
PROFI_PROFILE=info
```

или:

```env
PROFI_PROFILE=languages
```

Профиль хранит:

- persona;
- subject keywords;
- профильные stop-слова;
- remote-only policy;
- fallback templates.

Fallback применяется **только когда LLM недоступна/сломала формат/дала невалидный
текст**. Если работающая LLM осознанно вернула `skip`, шаблон вместо этого не
отправляется. И LLM-текст, и fallback проходят одинаковый post-check: контакты/
ссылки запрещены, длина 100–500 символов.

`PROFI_PERSONA`, `PROFI_SUBJECTS`, `PROFI_STOP_PATTERNS` сохранены как legacy
override'ы. `PROFI_PERSONA=info` соответствует `profile=info`, `lang` —
`profile=languages`.

Подробно: `profiles/README.md`.

## Текущее состояние

- `src/profi/main.py` — worker/CLI, цикл ленты 45–60 с, fast-path свежих заказов,
  чат-чек каждый N-й цикл;
- `src/profi/fastpath.py` — full gates, LLM/fallback decision, same-page send;
- `src/profi/integration/` — feed/order/respond/chat browser primitives;
- `src/profi/storage/` — SQLite state/idempotency;
- `src/profi/llm/` — glm/openai/anthropic-compatible providers;
- `main.py autopilot` — legacy/rollback consumer старых `draft=pending` кандидатов;
- `profiles/` — reusable business profiles.

## Настройка

```bash
cd ~/profi
uv sync
cp .env.example .env
uv run python -m profi llm-check
```

Chrome — отдельный persistent profile на аккаунт и свой CDP port. Рабочие часы
`PROFI_WORK_HOURS=8,23`: вне окна worker не reload'ит feed и не открывает заказы.
Сам Chrome может оставаться запущенным — это не означает 24/7 активность на Profi.

## Команды

```bash
uv run python -m profi                  # рабочий worker + fast-path
uv run python -m profi --once           # один scan-only цикл: details без auto-send
uv run python -m profi autopilot        # legacy/rollback consumer
uv run python -m profi llm-check
uv run python -m profi candidates
uv run python -m profi stats
uv run python -m profi fetch-details <id>
uv run python -m profi respond <id> --rate N --text '...' [--send]
uv run python -m profi note <id> --text '...'
uv run python -m profi sent|skip <id>
uv run python -m profi chats
uv run python -m profi chat-auto
uv run pytest
```

## Где что лежит

- `src/profi/` — engine: orchestration, browser, integrations, LLM, storage, fastpath;
- `profiles/` — бизнес-конфигурация оффера и fallback templates;
- `personas/` — LLM-идентичность преподавателя;
- `accounts/*.env` — конкретный аккаунт: profile, Chrome/CDP, DB, tariff;
- `data/*.db` — SQLite; `data/browser-profiles/` — Chrome sessions;
- `logs/` — runtime logs/screenshots;
- `ops/` — privacy-safe aggregate snapshots;
- `docs/` — architecture/spec/journal/backlog;
- `scripts/` — запуск аккаунтов, браузера, cron/diagnostics.

Приоритет бизнес-настроек: process env → `.env` → `profiles/<name>.toml` → engine defaults.
