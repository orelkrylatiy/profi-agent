# Daily ops snapshots

`ops/` содержит небольшие **санитизированные агрегированные отчёты**, которые можно безопасно хранить в этом публичном репозитории и потом разбирать через GitHub/ChatGPT.

## Быстрый запуск

Collector использует только стандартную библиотеку Python. **`uv run` не нужен** и для генерации отчёта не требуется доступ к PyPI.

### Windows / PowerShell

Из корня репозитория:

```powershell
python scripts\ops\daily_report.py --date today
```

За вчера:

```powershell
python scripts\ops\daily_report.py --date yesterday
```

Для конкретной даты:

```powershell
python scripts\ops\daily_report.py --date 2026-09-03
```

Успешный запуск печатает путь, например:

```text
ops\daily\2026-09-03.json
```

Проверить последний отчёт:

```powershell
Get-Content ops\latest.json
```

### Linux / VPS

Из корня репозитория:

```bash
python3 scripts/ops/daily_report.py --date today
```

За вчера:

```bash
python3 scripts/ops/daily_report.py --date yesterday
```

Проверить результат:

```bash
cat ops/latest.json
```

Collector создаёт/обновляет два файла:

```text
ops/daily/YYYY-MM-DD.json
ops/latest.json
```

Часовой пояс по умолчанию — `Asia/Yekaterinburg`. На Windows, где системная IANA timezone database может отсутствовать, для Екатеринбурга используется встроенный fallback UTC+05:00, поэтому устанавливать `tzdata` не требуется.

При необходимости можно указать timezone явно:

```bash
python3 scripts/ops/daily_report.py --date yesterday --timezone Asia/Yekaterinburg
```

## Что делать после генерации

Если запускаешь локально и хочешь, чтобы отчёт появился в GitHub:

```bash
git add ops/daily/YYYY-MM-DD.json ops/latest.json
git commit -m "ops: daily snapshot YYYY-MM-DD"
git push
```

## Автоматически: pre-commit hook

Чтобы свежий снапшот уезжал с КАЖДЫМ коммитом (руками ничего запускать не надо),
в репо есть хук `githooks/pre-commit`: перед коммитом он сам гоняет
`scripts/ops/daily_report.py --date today` и делает `git add` отчёта.

Активация — один раз на клон (Windows Git Bash / Linux / macOS одинаково):

```bash
git config core.hooksPath githooks
```

Нюансы:

- хук — `/bin/sh`, работает везде, где есть git; python ищет как `python3`, потом `python`;
- если генерация упала (например, лок БД во время отправки отклика), хук печатает
  предупреждение в stderr, но коммит НЕ блокирует — отчёт не гейт, а сайд-эффект;
- merge-коммиты не снапшотятся;
- `.gitattributes` держит `githooks/*` в LF, так что хук не ломается на клонах.

После push можно попросить ChatGPT, например:

```text
Посмотри ops/latest.json в profi-agent и разбери воронку, расходы и технические проблемы за день.
```

## Автоматический daily publish на VPS

Для чистого VPS-клона на `main` есть publisher:

```bash
bash scripts/ops/daily_publish.sh yesterday
```

Он сам:

1. проверяет, что текущая ветка совпадает с `OPS_PUBLISH_BRANCH`;
2. отказывается работать, если есть tracked-изменения вне `ops/`;
3. делает `git pull --ff-only`;
4. запускает collector обычным `python3`, без `uv` и без PyPI;
5. коммитит только дневной отчёт и `ops/latest.json`;
6. делает `git push`.

Переменные окружения:

```text
OPS_TIMEZONE=Asia/Yekaterinburg
OPS_PUBLISH_BRANCH=main
OPS_PYTHON=python3
```

Если на машине Python называется иначе, например `python`, можно запустить:

```bash
OPS_PYTHON=python bash scripts/ops/daily_publish.sh yesterday
```

## Cron

Пример: каждый день в 02:30 собрать и запушить отчёт за вчера:

```cron
30 2 * * * cd /root/profi-agent && OPS_TIMEZONE=Asia/Yekaterinburg bash scripts/ops/daily_publish.sh yesterday >> logs/ops-daily.log 2>&1
```

Если репозиторий лежит в другом месте, поменяй только путь после `cd`.

Для локальной разработки обычно достаточно запускать `daily_report.py` вручную. `daily_publish.sh` рассчитан прежде всего на чистый VPS-клон.

## Privacy contract

Collector работает по allow-list и никогда не копирует в отчёт сырые строки логов или свободный текст из БД.

В generated JSON не должны попадать:

- имена клиентов и другой PII;
- order id;
- тексты чатов или откликов;
- сырые URL;
- cookies, headers, API keys и tokens;
- сырые traceback/exception/log fragments.

Хранятся только агрегированные счётчики, технические статусы и revision кода.

Поскольку отчёт намеренно не содержит чувствительных данных и должен читаться через GitHub/ChatGPT, он хранится в plaintext. **Не добавляй в `ops/` зашифрованные или незашифрованные raw logs.** Если когда-нибудь понадобится сырой incident context, его нужно хранить отдельно от Git.

`logs/` и `data/` остаются в `.gitignore`. Это не мешает collector читать их локально или на VPS: `.gitignore` только запрещает Git отслеживать эти файлы.

## Что собирается

SQLite — основной источник бизнес-метрик:

- новые заказы из feed;
- созданные candidates и загруженные details;
- сгенерированные drafts;
- sent/unknown responses;
- recorded upfront spend;
- response modes;
- ответы репетитора в чатах;
- `needs_human`, chat send failures и injection-guard events;
- текущие candidate status/error counters.

Логи используются только для подсчёта заранее разрешённых технических сигнатур, например:

- `FEED_AUTH_COOLDOWN`;
- `FEED_CAPTURE_ERROR`;
- `BROWSER_OFFLINE` / `AUTH_REQUIRED`;
- `OPEN_FAIL`;
- `LLM_LIMIT`;
- `send_status=fail|unknown`;
- `database is locked`;
- traceback/tab-hygiene/CDP reconnect/browser-exit events.

Сами совпавшие строки логов в `ops/` не сохраняются.
