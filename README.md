# Контур A — воркер откликов Профи.ру

Читатель ленты + триаж + черновики; отправка всегда за человеком.
Спека: vault `01 Projects/Репетиторство/Спека — Контур A (воркер откликов).md`.

## Текущее состояние: milestone «читатель ленты»

Chrome (выделенный профиль) → reload ленты → перехват `BoSearchBoardItems` →
нормализация SNIPPET'ов → diff по `feed_seen` → hard-фильтры → лог.
LLM-триаж, открытие заказов и черновики — следующие шаги.

## Настройка

```bash
cd ~/profi
uv sync                # создаёт .venv, ставит playwright
```

Chrome скачивать не нужно: воркер использует системный Chrome с отдельным
user-data-dir (`~/profi/chrome-profile`) и CDP-портом 9223.

## Первый запуск

```bash
uv run python main.py --once
```

Воркер запустит Chrome с чистым профилем и откроет ленту. Залогинься в
Профи.ру в этом окне один раз — сессия живёт в профиле и переживает
перезапуски. Повтори `--once` — должен появиться лог ленты.

## Рабочий режим

```bash
uv run python main.py            # луп: цикл каждые 90–120 с, ждёт логин сам
```

## Ручной гейт (после появления кандидатов)

```bash
uv run python main.py candidates
uv run python main.py sent <order_id>
uv run python main.py skip <order_id>
```

## Где что лежит

- `data/profi.db` — SQLite: `feed_seen` (фингерпринт) + `candidates`;
- `logs/worker.log` — полный лог (DEBUG);
- `logs/feed_diag/` — дампы неудачных захватов фида.

Настройки (порт, интервалы, фильтры) — `config.py`.
