# Daily ops snapshots

`ops/` contains small **sanitized aggregate reports** that are safe to keep in this public repository and convenient to analyse later through GitHub/ChatGPT.

## Privacy contract

The collector uses an allow-list. It never copies raw log lines or free-form database text into the report.

The generated JSON must not contain:

- client names or other PII;
- order ids;
- chat/application text;
- raw URLs;
- cookies, headers, API keys or tokens;
- raw exceptions/log fragments.

Only aggregate counts, technical status names and the code revision are stored.

Because the report is intentionally non-sensitive and must remain readable through GitHub tooling, it is stored as plaintext. **Do not add encrypted raw logs to this directory.** If raw incident context is ever needed, keep it outside Git or move it to a separate protected workflow.

`logs/` and `data/` remain in `.gitignore`. This does not prevent the collector from reading them locally or on the VPS; `.gitignore` only controls what Git tracks.

## Manual report

Today:

```bash
uv run python scripts/ops/daily_report.py --date today
```

Yesterday:

```bash
uv run python scripts/ops/daily_report.py --date yesterday
```

The collector writes:

```text
ops/daily/YYYY-MM-DD.json
ops/latest.json
```

Default reporting timezone is `Asia/Yekaterinburg`; override with `--timezone`.

## Daily publish

For a clean VPS clone on `main`:

```bash
./scripts/ops/daily_publish.sh yesterday
```

The publisher:

1. refuses to run if tracked code/docs changes exist outside `ops/`;
2. performs `git pull --ff-only`;
3. generates the previous day's sanitized snapshot;
4. commits only the daily report and `ops/latest.json`;
5. pushes the configured branch.

Environment variables:

```text
OPS_TIMEZONE=Asia/Yekaterinburg
OPS_PUBLISH_BRANCH=main
```

## Cron example

Run once a day after the reporting day has definitely ended. On the current VPS setup, 02:30 is a conservative default:

```cron
30 2 * * * cd /root/profi-agent && OPS_TIMEZONE=Asia/Yekaterinburg ./scripts/ops/daily_publish.sh yesterday >> logs/ops-daily.log 2>&1
```

If the machine uses another repository path, change only the `cd` part.

For local development, it is usually better to run `daily_report.py` manually and use `daily_publish.sh` only from a clean clone.

## What is collected

SQLite is the primary source of business metrics:

- new feed orders;
- candidates created and details loaded;
- drafts generated;
- sent/unknown responses;
- recorded upfront spend;
- response modes;
- tutor chat replies;
- `needs_human`, chat send failures and injection-guard events;
- current candidate state/error counters.

Logs are used only for counts of known technical signatures, for example:

- `FEED_AUTH_COOLDOWN`;
- `FEED_CAPTURE_ERROR`;
- `BROWSER_OFFLINE` / `AUTH_REQUIRED`;
- `OPEN_FAIL`;
- `LLM_LIMIT`;
- `send_status=fail|unknown`;
- `database is locked`;
- traceback/tab-hygiene/CDP reconnect/browser-exit events.

No matching source line is persisted in `ops/`.
