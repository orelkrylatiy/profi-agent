"""Снимок состояния вкладки: body text, data-testid инвентарь, классы списков.

Чистое чтение DOM. Показывает, что отрисовалось после reload чатов/ленты
и какие якоря реально доступны для парсинга диалогов.
Запуск: uv run python scripts/diag/explore_dom.py [chats|feed]
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from profi import config
from profi.browser import is_feed_url

CDP = f"http://127.0.0.1:{config.CDP_PORT}"

JS = """
() => {
  const out = {url: location.href, title: document.title};
  out.bodyText = document.body.innerText.slice(0, 3000);
  out.testids = {};
  document.querySelectorAll('[data-testid]').forEach(el => {
    const id = el.getAttribute('data-testid');
    out.testids[id] = (out.testids[id] || 0) + 1;
  });
  // крупные списки: что похоже на перечень диалогов
  out.bigLists = [];
  document.querySelectorAll('ul, [role=list], [class*=list]').forEach(el => {
    if (el.children.length >= 3) {
      out.bigLists.push({
        tag: el.tagName, cls: (el.className || '').toString().slice(0, 80),
        children: el.children.length,
      });
    }
  });
  out.bigLists = out.bigLists.slice(0, 10);
  return out;
}
"""


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "chats"
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP, timeout=10_000)
        ctx = browser.contexts[0]
        pg = None
        for cand in ctx.pages:  # первая совпавшая (единообразно с остальными пробниками)
            try:
                url = cand.url
            except Exception:
                continue
            if which == "chats" and "/r.php" in url:
                pg = cand
                break
            if which == "feed" and is_feed_url(url):
                pg = cand
                break
        if pg is None:
            print(f"нет вкладки {which}")
            return
        data = pg.evaluate(JS)
        print("URL:", data["url"])
        print("TITLE:", data["title"])
        print("\n--- BODY TEXT (первые 1500) ---")
        print(data["bodyText"][:1500])
        print("\n--- data-testid инвентарь ---")
        for k, v in sorted(data["testids"].items()):
            print(f"  {v:>3}x {k}")
        print("\n--- крупные списки ---")
        for item in data["bigLists"]:
            print(f"  <{item['tag']}> children={item['children']} class={item['cls']}")


if __name__ == "__main__":
    sys.exit(main())
