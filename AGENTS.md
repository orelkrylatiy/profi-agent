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
uv run python main.py llm-check   # проверка LLM

# поднять аккаунт (браузер + воркер, идемпотентно):
bash scripts/run_lang.sh            # акк lang (Валерия, англ+исп, CDP :9224, data/lang.db)
bash scripts/run_info.sh            # акк info (информатика, CDP :9223, data/profi.db)
bash scripts/fix_lang_browser.sh    # починить зависший браузер lang
bash scripts/fix_info_worker.sh     # поднять info-воркер
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
main.py       — CLI: цикл воркера, autopilot, respond, llm-check, candidates, stats
browser.py    — Chrome over CDP (коннект к живому или launch), логин-стена
feed.py       — чтение ленты через перехват BoSearchBoardItems (пассивно)
filters.py    — hard-фильтры (предметы, дистанционка)
orders.py     — карточки заказов, тарифы, детали
respond.py    — заполнение формы отклика ЧЕЛОВЕЧЕСКИМИ инпутами (RULES §1)
llm.py        — мульти-провайдерный LLM (glm/openai/anthropic), ключи в .env
store.py      — SQLite: feed_seen, candidates, v_responses
config.py     — все настройки + env-переопределения
personas/     — промпты персон (info.md, lang.md)
accounts/     — <acc>.env (персона, порт, профиль, субъекты) + <acc>.ready
scripts/      — запуск/починка браузеров и воркеров, rhythm_keeper
data/         — <acc>.db (SQLite), rhythm_state.json, chats_state.json
logs/         — worker-<acc>.log, autopilot.log, rhythm.log, respond/ (скриншоты)
```

## Ключевые env (в accounts/<acc>.env и .env)

- `PROFI_PERSONA`, `PROFI_SUBJECTS`, `PROFI_CDP_PORT`, `PROFI_CHROME_PROFILE`, `PROFI_DB`
- `PROFI_CHROME_PATH` — путь к chrome-бинарю (на VPS — `scripts/chrome-vps.sh`);
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
