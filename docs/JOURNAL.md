# JOURNAL.md — журнал экспериментов (ведёт агент-аналитик)

Формат: дата, что делали, что наблюдали, вывод/следующий шаг.
Логи машинные: `logs/worker.log`, дампы захватов: `logs/feed_diag/`.

## 2026-08-31 — сессия 1

- Окружение: Mac, Chrome 151, профиль `data/chrome-profiles/main`,
  CDP 9333 поднят `scripts/start-chrome.sh`, вкладка «Заказы» (n.php) открыта,
  сессия профи живая. Проверено через `/json/list`.
- Правила владельца записаны в `RULES.md` (кастомные тексты, никаких
  консольных скриптов для действий, человеческий рандом, CDP-input only).
- Конфиг воркера приведён к 9333/main (был 9223/chrome-profile).
- M0: первый read-only цикл чтения ленты — результат см. ниже. (заполняется)

## 2026-08-31 — M0/M1: чтение ленты

**Отклонение от vault-спеки §8.1 (важно).** На живом билде поле
`operationName` в JSON-теле запроса ОТСУТСТВУЕТ. Имя операции сидит в самом
тексте запроса: `{"query":"#prfrtkn:webbo:<h>:<h>\\n query BoSearchBoardItems($filter:...)"}`.
Матчер `feed._operation_name()` теперь достаёт имя регэкспом из `query`,
поле `operationName` проверяется первым (обратная совместимость).
Vault-спеку §8.1 стоит поправить — не делал без разрешения владельца.

**Наблюдения живой ленты (профиль main):**
- За один reload ровно 1 запрос `BoSearchBoardItems`, приходит на ~+2.0 с
  после domcontentloaded. Окно 8 с достаточно.
- `variables`: `{allVerticals:true, searchQuery:'', searchEntities:[], pageSize:10,
  useSavedFilter:true, sort:'DEFAULT', filter:{}}` — cursor отсутствует →
  canonical-критерий §10.1 выполняется.
- Reload дополнительно триггерит мутации `SaveBoSearchViewedSnippet`
  (+2.2 с, +5.2 с) — сайт сам отмечает сниппеты просмотренными → ещё одно
  подтверждение, что серверному `isViewed` доверять нельзя, только свой store.
- Прочие операции при загрузке: BoPrepGeoCity, SetPrepOnlineStatus (~1/мин),
  BoProfileMe, BoSearchBoardFilter ×2, storiesPlaceholders, storiesTags.

**Результат M0 (01:17):** items=6 сырых → 3 SNIPPET; 3 NEW;
фильтры: 1 PASS (#93324326 «Олимпиады по информатике», 1600–3700 ₽,
Дистанционно·Москва), 2 SKIP (#92728800 бюджет 1900<2000; #93041518 вакансия).

**Результат M1 (3 цикла):** цикл 2 — 0 новых/изменённых (дедуп/идемпотентность
подтверждены), см. `logs/m1_run.log`.

**Правило интерпретации RULES про «скрипты в консоли»** (зафиксировано):
запрещены JS-действия через `page.evaluate`; `locator.click()`/`type()` в
Playwright — это настоящие CDP Input-события (isTrusted) и разрешены.

## 2026-08-31 — M2/M5: карточка заказа, форма отклика

**§33 спеки закрыт по живым наблюдениям:**
- Q1: за один reload ровно ОДИН `BoSearchBoardItems` (см. M0/M1 логи).
- Q2: `BoOrderScreen` очень богат — `data.orders[0].boOrderScreen`:
  price (цена отклика), tariffsBlock (defaultTariffType, isMonoTariff,
  tariffs[]), bidForms[0].bidSlideData (priceHash, paymentInfo,
  elements: stavka INPUT + comments4client TEXTAREA + edizms), params[]
  (описание/ученик/пожелания/адрес/дистанционно/детали). DOM добавляет:
  позицию отклика, профиль клиента (имя, «на Профи с», подтверждение
  номера, онлайн). Имя клиента — регэкспом по DOM-тексту.
- Q3: клик по карточке ВСЕГДА открывал новую вкладку (все пробы).

**Цепочка работающего v0.5:** PASS фильтров → candidate в БД →
авто-открытие → FullOrder (details_status=ready) — проверено на
#93324326 (`fetch-details`). Команды: `candidates`, `fetch-details <id>`,
`respond <id> --rate N --text '...' [--send]`.

**Форма отклика (probe_form + respond без --send):**
- CTA: `[data-testid="orderCard/tariffs"] >> text=Продолжить` (НЕ button).
- Окно `[data-testid="bid_window_container"]`: INPUT stavka (первый input),
  единица «час» дефолт, textarea 500 симв., футер «К оплате / баланс /
  Откликнуться».
- Посимвольный ввод чанками 3–9 символов, паузы 0.15–0.6 с — работает,
  подтверждено скриншотом (ставка 2500, текст 79/500).
- Баланс аккаунта: **1800 ₽** (хватит на 4 отклика по 367 ₽).

**Файлы:** дамбы/скриншоты — `logs/m2/`, `logs/m5/`, `logs/respond/`.
Скрипты-пробники: `scripts/diag_feed*.py`, `scripts/probe_order.py`,
`scripts/probe_form.py`.

**Неизвестное до первого реального отклика:** success-state после нажатия
«Откликнуться» (какой response подтверждает отправку) — узнаем в момент
первой супервизорной отправки; телеметрия (RPC + URL + скриншоты) пишется.
