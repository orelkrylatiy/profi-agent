# Business profiles

`profiles/` хранит бизнес-конфигурацию оффера отдельно от конкретного аккаунта,
Chrome и SQLite.

Главное правило:

> **profile = оффер/тип преподавателя, а не обязательно один предмет.**

Сейчас:

- `info.toml` — информатика / программирование;
- `languages.toml` — английский + испанский одним языковым оффером.

Если английский и испанский позже реально разойдутся по офферу, ставке, persona
или правилам отбора, их можно разделить без изменения engine.

## Формат

```toml
id = "languages"
persona = "lang"
remote_only = true
subject_keywords = ["английск", "испанск"]
stop_patterns = ["star-метод"]

[fallback]
enabled = true
templates = [
  "Здравствуйте! ...",
  "Добрый день! ...",
]
```

Поля:

- `persona` — `personas/<persona>.md` для LLM;
- `subject_keywords` — предметные подстроки hard-filter;
- `stop_patterns` — профильные stop-слова;
- `remote_only` — только дистанционные заказы;
- `fallback.enabled/templates` — резервные тексты fresh-order fast-path.

## Когда отправляется fallback

Fallback не заменяет бизнес-триаж. Порядок такой:

```text
snippet hard filters
  ↓
FullOrder gates
  ↓
LLM
  ├─ нормальный verdict=skip  → skipped, fallback НЕ используется
  ├─ нормальный verdict=send  → LLM text
  └─ LLM unavailable / limit / bad JSON / invalid send text
                               → profile fallback
```

Перед отправкой fallback проходит тот же post-check, что и LLM text:

- никаких телефонов, ссылок, e-mail/контактов;
- 100–500 символов;
- если >500, допустимо обрезать только по завершённому предложению;
- пустой/невалидный fallback приводит к terminal `failed`, а не к отправке мусора.

Выбор шаблона детерминирован по `order_id`: тексты варьируются между заказами,
но один и тот же заказ всегда получает один и тот же template. В SQLite сохраняется
`draft_source=llm|fallback`, поэтому эффективность источников можно сравнивать.

## Как аккаунт выбирает профиль

```env
PROFI_PROFILE=info
```

или:

```env
PROFI_PROFILE=languages
```

Account env хранит runtime-настройки:

```env
PROFI_PROFILE=languages
PROFI_CDP_PORT=9222
PROFI_DB=data/lang.db
PROFI_CHROME_PROFILE=data/chrome-profiles/lang
PROFI_RESPOND_MODE=commission
```

## Обратная совместимость

Старые override'ы остаются:

```env
PROFI_PERSONA=lang
PROFI_SUBJECTS=английск,испанск
PROFI_STOP_PATTERNS=...
```

Если `PROFI_PROFILE` не задан:

- `PROFI_PERSONA=info` → `profile=info`;
- `PROFI_PERSONA=lang` → `profile=languages`;
- неизвестная legacy persona работает без profile, как раньше.

Явно указанный, но отсутствующий/битый `PROFI_PROFILE` падает fail-closed: бот не
должен молча переключиться на другой предмет.

## Fast-path и rollback

Fallback реально используется только основным fresh-order flow:

```env
PROFI_FAST_PATH=1
```

При аварийном rollback:

```env
PROFI_FAST_PATH=0
```

worker снова только загружает details, а старый `autopilot` обрабатывает очередь.

## Где что живёт

```text
profiles/             бизнес-правила оффера + fallback
personas/             идентичность/контекст преподавателя для LLM
accounts/*.env        конкретный аккаунт, Chrome, DB, тариф, overrides
src/profi/            общий engine
```

Новый оффер в нормальном случае не требует правок browser/orders/respond-кода:
добавляются profile, при необходимости persona и account env.
