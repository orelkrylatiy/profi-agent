# Profi Agent Dashboard

Локальная/внутренняя визуализация поверх privacy-safe `ops/dashboard.json`.
Dashboard ничего не знает о cookies, логинах Profi, order ids, именах клиентов или raw logs.

## Что показывает

- **Обзор** — новые заказы, кандидаты, отправки, ответы, availability incidents, воронка и тренд.
- **Аккаунты** — health worker-а отдельно от live capability отклика (`READY`, `NO_BALANCE`, `COMMISSION_UNAVAILABLE`, `COMMISSION_DAILY_LIMIT`, `UI_UNKNOWN`).
- **A/B тесты** — assigned/evaluated/fallback/sent/replied, send rate, reply rate и основной `reply yield`.
- **Надёжность** — availability incidents, failed outcomes, canonical runtime events и накопившиеся ошибки state inventory.

## Почему Mantine

V1 использует `@mantine/core` + `@mantine/charts` (Recharts). Это даёт единый набор готовых компонентов, charts, responsive layout, dark theme и accessibility без отдельной Tailwind-инфраструктуры в Python-репозитории. Если продуктовый UI позже потребует полного контроля над каждым компонентом, можно перейти/добавить shadcn/ui; если графики станут существенно сложнее — отдельно рассмотреть Apache ECharts.

## Данные

`scripts/ops/dashboard_export.py` строит `ops/dashboard.json` из:

1. `ops/latest.json` и `ops/daily/*.json` — агрегированная история;
2. локальных account SQLite DB — только агрегаты `v_prompt_experiments`;
3. локальных `data/<account>.capability.json` — только публичное состояние capability.

Публикуемые аккаунты получают псевдонимы `account_1`, `account_2`, ... . Точный баланс и стоимость отклика остаются только локально; dashboard получает лишь `balance_known` / `price_known`.

`daily_publish.sh` автоматически обновляет dataset вместе с дневным snapshot.

## Запуск

Из `dashboard/`:

```bash
npm install
npm run dev
```

По умолчанию frontend запрашивает `/ops/dashboard.json`. Для отдельного хостинга можно задать:

```bash
VITE_DASHBOARD_DATA_URL=https://example.internal/ops/dashboard.json npm run build
```

Если раздавать корень репозитория статическим сервером, production build в `dashboard/dist/` также сможет читать `/ops/dashboard.json`.

## Сборка

```bash
npm run build
```

Сборка проверяется отдельным `dashboard-build` job в GitHub Actions.
