"""Reload + полный захват graphql/RPC операций с именами и телами (read-only).

Reload вкладки — штатная команда браузера (RULES §1). Ловим каждый
/graphql: имя операции, variables (обрезано), статус, верхние ключи data,
число items. И каждый /backoffice/api/* вызов (префикс, не точное
равенство — claimOrder и прочие суффиксы). Печатаем в порядке прилёта.
Запуск: uv run python scripts/diag/explore_reload.py [chats|feed]
"""

from __future__ import annotations

import json
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from profi import config
from profi.browser import is_feed_url
from profi.integration.feed import _operation_name

CDP = f"http://127.0.0.1:{config.CDP_PORT}"
WATCH_S = 30


def op_name(req) -> str:
    """Имя graphql-операции (контракт общий с воркером: feed._operation_name)."""
    try:
        return _operation_name(req.post_data_json) or "?"
    except Exception:
        return "?"


def summarize(resp) -> str:
    """Компактная сводка ответа: ключи data + счётчики списков."""
    try:
        j = resp.json()
    except Exception:
        return "не-JSON"
    data = j.get("data")
    if data is None:
        return f"errors={str(j.get('errors'))[:150]}"
    parts = []
    for k, v in data.items():
        if isinstance(v, list):
            parts.append(f"{k}[{len(v)}]")
        elif isinstance(v, dict):
            sub = []
            for kk, vv in list(v.items())[:8]:
                if isinstance(vv, list):
                    sub.append(f"{kk}[{len(vv)}]")
                elif isinstance(vv, dict):
                    sub.append(kk)
                else:
                    s = str(vv)
                    sub.append(f"{kk}={s[:24]}" if s and not s.startswith("{") else kk)
            parts.append(f"{k}{{{','.join(sub)}}}")
        else:
            parts.append(f"{k}={str(v)[:30]}")
    return " ".join(parts)[:400]


def watch(page, tag: str, t0: float, out: list) -> None:
    def on_response(resp) -> None:
        try:
            u = urlparse(resp.url)
            if u.path == "/graphql":
                req = resp.request
                vars_ = ""
                try:
                    v = (req.post_data_json or {}).get("variables")
                    if v is not None:
                        vars_ = json.dumps(v, ensure_ascii=False)[:150]
                except Exception:
                    pass
                out.append(
                    f"+{time.monotonic() - t0:6.1f}s [{tag}] GQL {op_name(resp.request):<38} "
                    f"{resp.status} {summarize(resp)} | vars: {vars_}"
                )
            elif u.path.startswith("/backoffice/api/") and resp.request.resource_type in (
                "xhr",
                "fetch",
            ):
                body = ""
                try:
                    body = (resp.request.post_data or "")[:150]
                except Exception:
                    pass
                out.append(
                    f"+{time.monotonic() - t0:6.1f}s [{tag}] RPC {resp.request.method} "
                    f"{u.path[:60]} {resp.status} body: {body}"
                )
        except Exception as e:
            out.append(f"[{tag}] err {e}")

    page.on("response", on_response)
    page.reload(wait_until="domcontentloaded", timeout=45_000)


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "chats"
    out: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP, timeout=10_000)
        ctx = browser.contexts[0]
        target = None
        for pg in ctx.pages:
            try:
                url = pg.url
            except Exception:
                continue
            if which == "chats" and "/r.php" in url:
                target = pg
                break
            if which == "feed" and is_feed_url(url):
                target = pg
                break
        if target is None:
            print(f"вкладка {which} не найдена")
            return
        t0 = time.monotonic()
        watch(target, which, t0=t0, out=out)
        deadline = time.monotonic() + WATCH_S
        while time.monotonic() < deadline:
            time.sleep(0.3)
            while out:
                print(out.pop(0))
        while out:
            print(out.pop(0))
        print("--- конец окна ---")


if __name__ == "__main__":
    sys.exit(main())
