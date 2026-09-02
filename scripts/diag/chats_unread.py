"""Дешёвая проверка чатов r.php без LLM (zero-token).

Read-only: своя вкладка, читаем DOM, закрываем.
Ищет признаки непрочитанных: бейдж-счётчик у пункта «Чаты», классы
unread/badge/counter в списке диалогов. Плюс детект «список изменился»
через state-файл (hash текста списка).

Выход: одна строка JSON на stdout:
  {"unread": N, "chats": M, "changed": true|false, "ok": true}
  {"ok": false, "error": "..."}   — браузер мёртв и не поднялся
Exit-код всегда 0 (ошибки внутри ok:false, чтобы не ломать триггер).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from profi import config

STATE = (
    Path(
        config.DATA_DIR
        if hasattr(config, "DATA_DIR")
        else Path(__file__).resolve().parent.parent / "data"
    )
    / "chats_state.json"
)


def out(d: dict) -> None:
    print(json.dumps(d, ensure_ascii=False))


def main() -> int:
    try:
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.connect_over_cdp(
                f"http://127.0.0.1:{config.CDP_PORT}", timeout=10_000
            )
        except Exception:
            out({"ok": False, "error": "cdp_dead"})
            return 0
        ctx = browser.contexts[0]
        page = ctx.new_page()
        try:
            page.goto(
                "https://profi.ru/backoffice/r.php", wait_until="domcontentloaded", timeout=45_000
            )
            page.wait_for_timeout(4_000)
            html = page.content()
            body = page.locator("body").inner_text(timeout=8_000)

            # 1) бейдж у пункта «Чаты» в навигации: число рядом
            badge = 0
            m = re.search(r"Чаты[^\d]{0,20}(\d{1,3})\b", body)
            if m:
                badge = int(m.group(1))

            # 2) классы unread/badge в списке диалогов
            unread_els = len(re.findall(r'class="[^"]*(?:unread|is-unread|badge)[^"]*"', html))

            # 3) список диалогов — секция после «Чаты» до «Анкета/Поддержка»
            list_txt = ""
            m2 = re.search(r"Чаты\n(.*?)(?:Анкета|Поддержка)", body, re.S)
            if m2:
                list_txt = m2.group(1).strip()
            digest = hashlib.sha256(list_txt.encode()).hexdigest()[:16]

            # state
            prev = None
            if STATE.exists():
                try:
                    prev = json.loads(STATE.read_text()).get("digest")
                except Exception:
                    pass
            STATE.write_text(json.dumps({"digest": digest, "ts": int(time.time())}))

            unread = max(badge, unread_els)
            out(
                {
                    "ok": True,
                    "unread": unread,
                    "badge": badge,
                    "unread_els": unread_els,
                    "changed": bool(list_txt) and digest != prev,
                    "list_len": len(list_txt),
                }
            )
        finally:
            page.close()
            pw.stop()
    except Exception as e:
        out({"ok": False, "error": str(e)[:120]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
