# AGENTS.md — profi-agent (Контур A: автоотклики Профи.ру)

Перед любой работой с браузером/откликами читать `RULES.md` — он обязателен
и главнее этого файла. Спека: `docs/SPEC.md`, журнал: `docs/JOURNAL.md`.

## Что это

Автономный воркер откликов на Профи.ру: лента заказов → hard-фильтры →
LLM-триаж и кастомный текст отклика → отправка с денежными гейтами.
Мультиаккаунтно: **один аккаунт = одна персона = свой env, профиль Chrome, CDP-порт и БД**.

## Запуск (VPS, здесь)

```bash
cd /root/profi-agent
uv sync
cp .env.example .env        # ZAI_API_KEY, GLM_BASE_URL, LLM_MODEL
uv run python -m profi llm-check   # проверка LLM

# поднять аккаунт (браузер + воркер, идемпотентно) — generic, по accounts/<acc>.env:
bash scripts/account/run_account.sh lang    # акк lang (Валерия, англ+исп, CDP :9224, data/lang.db)
bash scripts/account/run_account.sh info    # акк info (информатика, CDP :9223, data/profi.db)
bash scripts/browser/fix_browser.sh lang    # починить зависший браузер lang
bash scripts/account/fix_worker.sh info     # перезапустить info-воркер
```

## Крон (пользователь root)

- `*/15 * * * *` `scripts/rhythm_keeper.sh` — живость всех `accounts/*.env`,
  «человеческий ритм» (паузы 01–14 МСК), лог `logs/rhythm.log`
- `18,48 * * * *` `/root/profi-autopilot-accounts.sh` — автопилот по всем
  `accounts/*.ready` (LLM-триаж + отправка), лог `logs/autopilot.log`

**Отключить аккаунт**: переименовать `accounts/<acc>.env` и `<acc>.ready`
в `*.disabled` — кроны его перестанут трогать.

## Структура

```
src/profi/          — пакет (ставится через uv sync, editable):
  main.py           — CLI и оркестрация: цикл воркера, autopilot, chats/chat-auto
  config.py         — все настройки + env-переопределения (якорь: PROJECT_DIR = корень репо)
  filters.py        — hard-фильтры (предметы, дистанционка)
  browser/          — Chrome over CDP: manager (коннект к живому или launch), логин-стена
  integration/      — Профи.ру: feed (перехват BoSearchBoardItems), orders (карточки),
                      respond (форма ЧЕЛОВЕЧЕСКИМИ инпутами, RULES §1), chat (чаты)
  storage/          — SQLite: feed_seen, candidates, chat_log, v_responses
  llm/              — мульти-провайдерный LLM (glm/openai/anthropic), ключи в .env
  models/           — OrderSnippet, FeedSnapshot, FilterVerdict
  utils/            — human_pause (человеческий темп), textguard (анти-инъекция)
personas/           — промпты персон (info.md, lang.md)
accounts/           — <acc>.env (персона, порт, профиль, субъекты) + <acc>.ready
scripts/            — точки входа планировщиков: rhythm_keeper.sh (VPS cron),
                      autopilot_cron.sh (Mac launchd), chat_cron.sh (Mac launchd
                      com.profi.chats, 4 мин: chats_unread.py → chat-auto)
  account/          — run_account.sh <acc>, fix_worker.sh <acc>
  browser/          — start-chrome.sh (Mac), chrome-vps.sh, launch_account_browser.sh,
                      fix_browser.sh <acc>
  diag/             — read-only пробники: diag_feed2, probe_order/form/chat, chats_unread
data/               — <acc>.db (SQLite), browser-profiles/<acc>, rhythm_state.json
logs/               — worker-<acc>.log, autopilot.log, rhythm.log, respond/ (скриншоты)
```

## Ключевые env (в accounts/<acc>.env и .env)

- `PROFI_PERSONA`, `PROFI_SUBJECTS`, `PROFI_CDP_PORT`, `PROFI_CHROME_PROFILE`, `PROFI_DB`
- `PROFI_CHROME_PATH` — путь к chrome-бинарю (на VPS — `scripts/browser/chrome-vps.sh`);
  дефолт в config.py — мак-путь, на VPS ОБЯЗАТЕЛЬНО переопределять
- `PROFI_RESPOND_MODE` — тариф отклика: `pay` (платный, дефолт) | `commission`
  (через комиссию Profi; если тариф недоступен аккаунту — отправка отменяется)
- LLM: `ZAI_API_KEY`/`GLM_API_KEY`, `GLM_BASE_URL`, `LLM_MODEL`
  (сейчас: `glm-5.3-flash` на coding-эндпоинте — у старших моделей кончается квота раньше)

## Гейты безопасности (RULES.md §2)

- лимит 3 платных отправки/день, потолок цены отклика 500 ₽ (`MAX_RESPONSE_PRICE_RUB`)
- `--send` — только явное разрешение; тексты всегда кастомные и честные
- ставка в форме: `config.RATE`

## Известные грабли (VPS)

- 1.6 ГБ RAM: два акка + автопилот могут выжрать память → Chrome крашится,
  CDP-рукопожатие виснет. Симптом: `ws connected` без ответа, «Chrome завершился
  сразу». Лечение: убить хромы, снять `Singleton*` в профиле, поднять заново.
- `pkill -f` с паттерном из собственной команды убивает сам exec — используй
  class-трюк: `pkill -f "922[3]"`.
- Лимит z.ai месячный — при 429 (code 1310) смотреть, на какой модели: у
  `glm-5.3-flash` квота отдельная и живёт дольше.
