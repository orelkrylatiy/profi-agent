"""История сети страницы через Performance API (чистое чтение, ноль действий).

performance.getEntriesByType('resource') хранит ВСЕ запросы страницы с момента
её загрузки: видим полный граф — какие URL, как часто (deltas startTime),
какой initiatorType (fetch/xhr/other=ws), responseStatus. Это отвечает:
- поллит ли лента сама (ритм повторяющихся /graphql);
- есть ли у страницы WS/SSE-канал (wss:// / eventsource);
- что реально запрашивала order-вкладка и чаты.
"""

from __future__ import annotations

import sys
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from profi import config

CDP = f"http://127.0.0.1:{config.CDP_PORT}"

JS = """
() => {
  const entries = performance.getEntriesByType('resource')
    .map(e => ({
      name: e.name,
      type: e.initiatorType,
      start: Math.round(e.startTime),
      dur: Math.round(e.duration),
      status: e.responseStatus === undefined ? null : e.responseStatus,
      size: e.transferSize,
    }))
    .filter(e => {
      const n = e.name;
      return n.includes('/graphql') || n.includes('backoffice') ||
             n.startsWith('wss://') || n.includes('sse') || n.includes('poll') ||
             n.includes('sock') || n.includes('pusher') || n.includes('centrifugo');
    });
  const nav = performance.getEntriesByType('navigation')[0];
  return {
    loaded_ago_s: nav ? Math.round((performance.now() - nav.startTime) / 1000) : null,
    visibility: document.visibilityState,
    has_focus: document.hasFocus(),
    entries,
  };
}
"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP, timeout=10_000)
        ctx = browser.contexts[0]
        for pg in ctx.pages:
            # чтение url/тегирование — в том же try, что и evaluate:
            # вкладка могла закрыться между итерациями
            try:
                url = pg.url
                if "profi.ru/backoffice" not in url:
                    continue
                tag = "chats" if "/r.php" in url else ("order" if "o=" in url else "feed")
                q = parse_qs(urlparse(url).query)
                if q.get("o"):
                    tag += f"({q['o'][0]})"
                data = pg.evaluate(JS)
            except Exception as e:
                print(f"== вкладка закрылась/недоступна: {e}")
                continue
            print(
                f"\n===== {tag} | загружена {data['loaded_ago_s']}s назад | "
                f"visibility={data['visibility']} focus={data['has_focus']}"
            )
            gql = [e for e in data["entries"] if "/graphql" in e["name"]]
            other = [e for e in data["entries"] if "/graphql" not in e["name"]]
            print(f"  /graphql всего: {len(gql)}")
            prev = None
            for e in gql:
                delta = f"+{e['start'] - prev}s" if prev is not None else ""
                prev = e["start"]
                print(
                    f"    t={e['start']:>7} {delta:>8} {e['type']:<6} "
                    f"status={e['status']} dur={e['dur']}ms size={e['size']}"
                )
            if other:
                print(f"  прочее ({len(other)}):")
                for e in other[:25]:
                    print(f"    t={e['start']:>7} {e['type']:<8} {e['status']} {e['name'][:110]}")


if __name__ == "__main__":
    sys.exit(main())
