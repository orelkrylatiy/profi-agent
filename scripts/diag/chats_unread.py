"""Дешёвая проверка чатов r.php без LLM (zero-token).

Read-only: своя вкладка, читаем DOM, закрываем.
Непрочитанные считаем ТОЛЬКО по карточкам диалогов (счётчик перед временем).
Число рядом с «Чаты» в навигации — баланс кошелька, НЕ трогаем (был баг:
582 ₽ принимались за 582 непрочитанных).
Плюс детект «список изменился» через state-файл (hash текста секции).

Выход: одна строка JSON на stdout:
  {"unread": N, "dialogs": M, "names": [...], "changed": true|false, "ok": true}
  {"ok": false, "error": "..."}   — браузер мёртв, не поднялся или нерабочие часы
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
from profi.utils import in_work_hours

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
    if not in_work_hours():
        # вне рабочих часов браузер не открываем; chat_cron.sh на ok:false
        # просто выходит (RULES: 8–23)
        out({"ok": False, "error": "нерабочие часы"})
        return 0
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
            body = page.locator("body").inner_text(timeout=8_000)

            # Живой факт лэйаута (2026-09-02): навигация «Заказы ⏎ Чаты ⏎ 582 ₽ ⏎
            # Анкета ⏎ Поддержка» — число рядом с «Чаты» это БАЛАНС КОШЕЛЬКА,
            # а не непрочитанные. Считаем непрочитанные только по карточкам
            # диалогов: «<буква-аватар> ⏎ ⏎ <имя> ⏎ <превью> ⏎ <счётчик> ⏎ <время>».
            # Время бывает: 20:51, Вчера, Вт (день недели), 2 окт — превью
            # любой длины (был баг: длинные превью роняли весь матч строки),
            # день недели с ЗАГЛАВНОЙ буквы (был баг: «Вт» не брался классом
            # [а-яё] — заглавная кириллица живёт в другом диапазоне).
            rows = re.findall(
                r"\n([А-ЯЁA-Z])\n\n([^\n]{1,60})\n([^\n]*)\n(\d{1,3})\n"
                r"(\d{1,2}:\d{2}|[Вв]чера|[Сс]егодня|[А-Яа-яёЁ]{1,2}|\d{1,2}\s[А-Яа-яёЁ]{2,3})\n",
                body,
            )
            counters_unread = sum(1 for r in rows if int(r[3]) > 0)

            # Второй сигнал: бейдж у пункта «Чаты» в навигации. Бейдж стоит
            # ПЕРЕД именем пункта («1 ⏎ Поддержка»), число после «Чаты» —
            # это баланс кошелька, его не трогаем. Бейдж Чатов сейчас пуст,
            # но при непрочитанных появится — ловим на будущее.
            m = re.search(r"(?:^|\n)(\d{1,3})\nЧаты\n", body)
            badge_chats = int(m.group(1)) if m else 0

            unread = max(counters_unread, badge_chats)

            # digest секции контента (после навигации) — «список изменился»
            anchor = body.find("Найти заказ")
            section = body[anchor:] if anchor != -1 else body[-2000:]
            digest = hashlib.sha256(section.encode()).hexdigest()[:16]

            # state
            prev = None
            if STATE.exists():
                try:
                    prev = json.loads(STATE.read_text()).get("digest")
                except Exception:
                    pass
            STATE.write_text(json.dumps({"digest": digest, "ts": int(time.time())}))

            out(
                {
                    "ok": True,
                    "unread": unread,
                    "badge": badge_chats,
                    "dialogs": len(rows),
                    "names": [r[1] for r in rows][:10],
                    "changed": bool(section) and digest != prev,
                    "list_len": len(section),
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
