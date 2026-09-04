# Business profiles

`profiles/` хранит бизнес-конфигурацию анкеты отдельно от конкретного аккаунта и браузера.

Главное правило:

> **profile = оффер/тип преподавателя, а не обязательно один предмет.**

Поэтому сейчас есть:

- `info.toml` — информатика / программирование;
- `languages.toml` — общий языковой профиль для английского + испанского.

Если английский и испанский позже начнут отличаться по офферу, ставке, персоне или правилам отбора, их можно будет разделить на два профиля без изменения engine.

## Что хранится в profile

```toml
id = "languages"
persona = "lang"
remote_only = true
subject_keywords = ["английск", "испанск"]
stop_patterns = ["star-метод"]

[fallback]
enabled = true
templates = [
  "...",
]
```

Поля:

- `persona` — файл `personas/<persona>.md` для LLM;
- `subject_keywords` — предметные подстроки для hard-filter;
- `stop_patterns` — стоп-слова именно этого бизнес-профиля;
- `remote_only` — пропускать только дистанционные заказы;
- `fallback.templates` — библиотека безопасных шаблонных откликов на будущее.

Fallback-тексты **уже хранятся в профиле, но пока автоматически не отправляются**. Автоматический fallback при недоступной LLM будет подключаться вместе с fast-path, чтобы изменение поведения отправки было явным и тестируемым.

Общие правила, не зависящие от предмета (`VACANCY_PATTERNS`, бартер, special-needs, денежные лимиты, work hours), остаются в `src/profi/config.py`.

## Как аккаунт выбирает профиль

Рекомендуемый вариант в `accounts/<account>.env`:

```env
PROFI_PROFILE=info
```

или:

```env
PROFI_PROFILE=languages
```

Аккаунт при этом продолжает хранить только runtime-настройки: Chrome profile, CDP port, DB, тариф и т.д.

Пример концептуально:

```env
PROFI_PROFILE=languages
PROFI_CDP_PORT=9222
PROFI_DB=data/lang.db
PROFI_CHROME_PROFILE=data/chrome-profiles/avito
PROFI_RESPOND_MODE=commission
```

## Обратная совместимость

Старые переменные не удалены:

```env
PROFI_PERSONA=lang
PROFI_SUBJECTS=английск,испанск
PROFI_STOP_PATTERNS=...
```

Они имеют приоритет над значениями profile. Это позволяет мигрировать аккаунты постепенно.

Если `PROFI_PROFILE` не задан:

- legacy `PROFI_PERSONA=info` автоматически выбирает `profile=info`;
- legacy `PROFI_PERSONA=lang` автоматически выбирает `profile=languages`;
- для неизвестной legacy persona остаётся старое поведение без profile.

Если `PROFI_PROFILE` задан явно, но файл отсутствует или невалиден, запуск падает fail-closed вместо молчаливого выбора неправильного оффера.

## Где что должно жить

```text
profiles/             бизнес-правила оффера
personas/             идентичность и LLM-контекст преподавателя
accounts/*.env        конкретный аккаунт/Chrome/DB/тариф
src/profi/            общий engine
```

Новый предмет/оффер в нормальном случае не должен требовать изменения `filters.py`, `orders.py`, `respond.py` или browser-кода: добавляется профиль, persona при необходимости и account env.
