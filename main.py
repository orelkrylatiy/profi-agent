"""Контур A — milestone «читатель ленты» (спека разд. 31, до LLM-триажа).

Цикл (single-flight, спека разд. 27):
  health → reload + перехват BoSearchBoardItems → нормализация →
  diff по feed_seen → hard filter → лог. Ничего не открывает и не отправляет.

Использование:
  uv run python main.py --once            # один цикл, для проверки
  uv run python main.py                   # рабочий цикл 90–120 с (ждёт логин сам)
  uv run python main.py candidates        # список кандидатов
  uv run python main.py sent <order_id>   # ручной гейт
  uv run python main.py skip <order_id>   # ручной гейт
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime

import config
import store as store_mod
from browser import AUTH_REQUIRED, BROWSER_OFFLINE, BrowserManager
from feed import FeedAmbiguous, FeedAuthError, FeedCapture, FeedCaptureError
from filters import hard_filter
from orders import OrderOpenError, extract_dom_texts, extract_full_order, human_pause, open_candidate

log = logging.getLogger("profi.main")

_login_hint_shown = False


def setup_logging() -> None:
    config.LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(config.LOG_LEVEL)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    fileh = logging.FileHandler(config.LOG_DIR / "worker.log", encoding="utf-8")
    fileh.setFormatter(fmt)
    fileh.setLevel(logging.DEBUG)
    root.addHandler(fileh)


def show_login_hint() -> None:
    global _login_hint_shown
    if not _login_hint_shown:
        log.info(">>> Залогинься в Профи.ру в открывшемся Chrome — воркер подхватит сессию сам.")
        _login_hint_shown = True


def save_capture_diag(diag: list[dict], err: str) -> None:
    if not diag:
        return
    diag_dir = config.LOG_DIR / "feed_diag"
    diag_dir.mkdir(parents=True, exist_ok=True)
    path = diag_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(
        json.dumps({"error": err, "candidates": diag}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("диагностика захвата сохранена: %s", path)


def load_details(bm: BrowserManager, store: store_mod.Store, order_id: str) -> str:
    """Открыть заказ → BoOrderScreen → FullOrder → UPDATE candidates (спека §19-22).

    Одна order-вкладка за раз, закрывается после обработки.
    """
    try:
        human_pause()
        ctx = bm._default_context()  # noqa: SLF001 — контекст принадлежит воркеру
        order_page, captured = open_candidate(ctx, bm.page, order_id)
    except OrderOpenError as e:
        log.error("открытие #%s не удалось: %s", order_id, e)
        store.update_details(order_id, "error", None)
        return "DETAILS_ERROR"
    try:
        dom = extract_dom_texts(order_page)
        if not captured:
            raise OrderOpenError("BoOrderScreen не пойман в новой вкладке")
        full = extract_full_order(captured[0].json(), dom.get("container_text"))
        store.update_details(order_id, "ready", json.dumps(full, ensure_ascii=False))
        log.info(
            "#%s: детали готовы | отклик %s ₽ | тариф %s | позиция %s | клиент %s",
            order_id,
            full.get("bid_price"),
            full.get("tariff_default"),
            full.get("competition_position"),
            full.get("client_block_dom", {}).get("name"),
        )
        return "DETAILS_READY"
    except Exception as e:
        log.error("извлечение деталей #%s упало: %s", order_id, e)
        store.update_details(order_id, "error", None)
        return "DETAILS_ERROR"
    finally:
        try:
            time.sleep(1.5)
            order_page.close(run_before_unload=False)
        except Exception:
            pass


def run_cycle(bm: BrowserManager, store: store_mod.Store) -> str:
    """Один worker cycle. Возвращает состояние, в котором остановились."""
    state = bm.ensure_ready()
    if state != "READY":
        if state == AUTH_REQUIRED:
            show_login_hint()
        else:
            log.warning("состояние %s — пропускаю цикл", state)
        return state

    capture = FeedCapture(bm.page)
    try:
        snap = capture.reload_and_capture()
    except FeedAuthError as e:
        # 401/403 на graphql: сессия или антибот. НЕ дёргаем ленту 30 с
        # (RULES.md §3): cooldown AUTH_COOLDOWN_S обрабатывает run_loop.
        log.error("FEED_AUTH_COOLDOWN: %s — пауза %d мин", e, config.AUTH_COOLDOWN_S // 60)
        return "FEED_AUTH_COOLDOWN"
    except FeedAmbiguous as e:
        log.error("FEED_AMBIGUOUS: %s", e)
        save_capture_diag(capture.last_diag, str(e))
        return "FEED_AMBIGUOUS"
    except FeedCaptureError as e:
        log.error("FEED_CAPTURE_ERROR: %s", e)
        save_capture_diag(capture.last_diag, str(e))
        return "FEED_CAPTURE_ERROR"
    except Exception:
        log.exception("неожиданная ошибка цикла — не умираем")
        return "ERROR"

    log.info(
        "feed: items=%d totalCount=%s serverTs=%s",
        len(snap.snippets),
        snap.total_count,
        snap.server_ts,
    )

    fresh = passed = skipped = 0
    for s in snap.snippets:
        status = store.register_feed_seen(s.id, s.last_update)
        if status == "UNCHANGED":
            continue
        fresh += 1
        verdict = hard_filter(s)
        if verdict.passed:
            passed += 1
            if config.AUTO_CREATE_CANDIDATES and status == "NEW":
                store.create_candidate(s, "rule-pass (LLM-триаж — M3)", None)
                log.info("#%s → candidate", s.id)
                if config.AUTO_LOAD_DETAILS:
                    load_details(bm, store, s.id)
        else:
            skipped += 1
        badge = ",".join(s.badges) if s.badges else "-"
        log.info(
            "%-7s #%s [%s] %s | %s | geo: %s | badges=%s | %s: %s",
            status,
            s.id,
            "fresh" if s.is_fresh else "old",
            (s.title or "")[:60],
            s.price_raw or "-",
            f"{s.geo_remote or ''} {s.geo_remote_suffix or ''}".strip() or "-",
            badge,
            "PASS" if verdict.passed else "SKIP",
            verdict.reason,
        )

    log.info("итог цикла: новых/изменённых=%d, pass=%d, skip=%d", fresh, passed, skipped)
    return "OK"


def run_loop(max_cycles: int | None = None) -> int:
    bm = BrowserManager()
    store = store_mod.Store(config.DB_PATH)
    done = 0
    try:
        state = bm.start()
        if state == BROWSER_OFFLINE:
            return 1
        log.info("стартовое состояние: %s (max_cycles=%s)", state, max_cycles)
        if state == AUTH_REQUIRED:
            show_login_hint()

        while True:
            state = run_cycle(bm, store)
            done += 1
            if max_cycles is not None and done >= max_cycles:
                log.info("отработано %d циклов — выхожу", done)
                return 0
            if state == "FEED_AUTH_COOLDOWN":
                log.warning(
                    "401/403: стоп мониторинга на %d мин (RULES.md). Проверь браузер руками.",
                    config.AUTH_COOLDOWN_S // 60,
                )
                time.sleep(config.AUTH_COOLDOWN_S)
                continue
            if state == AUTH_REQUIRED:
                time.sleep(config.AUTH_WAIT_S)
                continue
            if state == BROWSER_OFFLINE:
                time.sleep(10)
                continue
            interval = random.randint(config.RELOAD_INTERVAL_MIN_S, config.RELOAD_INTERVAL_MAX_S)
            log.info("следующий цикл через %d с", interval)
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("остановлено человеком")
        return 0
    finally:
        bm.shutdown()
        store.close()


def run_once() -> int:
    bm = BrowserManager()
    store = store_mod.Store(config.DB_PATH)
    try:
        state = bm.start()
        if state == BROWSER_OFFLINE:
            return 1
        log.info("стартовое состояние: %s", state)
        state = run_cycle(bm, store)
        if state == AUTH_REQUIRED:
            log.info(">>> Залогинься в Профи.ру в открывшемся Chrome и запусти ещё раз (или луп без --once).")
            return 2
        return 0 if state == "OK" else 1
    except KeyboardInterrupt:
        return 0
    finally:
        bm.shutdown()
        store.close()


def run_respond(order_id: str, rate: int, text: str, send: bool) -> int:
    """Заполнить форму отклика (и опционально отправить — ПЛАТНО).

    RULES.md: кастомный текст обязателен; финальный клик только с --send;
    первый реальный отклик — после подтверждения владельцем.
    """
    import respond as respond_mod
    from datetime import datetime

    out_dir = config.LOG_DIR / "respond"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H%M%S")

    bm = BrowserManager()
    store = store_mod.Store(config.DB_PATH)
    order_page = None
    try:
        state = bm.start()
        if state != "READY":
            log.error("сессия не READY: %s", state)
            return 2
        ctx = bm._default_context()  # noqa: SLF001
        order_page = respond_mod.open_respond_form(ctx, bm.page, order_id)
        footer = respond_mod.fill_form(order_page, rate, text)
        log.info("форма заполнена: к оплате=%s баланс=%s кнопка=%s",
                 footer.get("to_pay"), footer.get("balance_seen"), footer.get("send_button_found"))
        shot = out_dir / f"{order_id}_{stamp}_filled.png"
        order_page.screenshot(path=str(shot), full_page=True)

        # черновик в БД
        now = int(time.time())
        store.conn.execute(
            "UPDATE candidates SET draft_status='generated', draft_text=?, draft_generated_at=?, "
            "updated_at=? WHERE order_id=?",
            (text, now, now, order_id),
        )
        store.conn.commit()

        if not send:
            log.info("ОТПРАВКА НЕ ВЫПОЛНЕНА (нет --send). Скриншот: %s", shot)
            time.sleep(2)
            order_page.close(run_before_unload=False)
            return 0

        if footer.get("to_pay") is None:
            log.error("не смог прочитать «К оплате» — отмена отправки")
            order_page.close(run_before_unload=False)
            return 1

        # денежные предохранители (RULES.md §2, ревью P0-2)
        if footer["to_pay"] > config.MAX_RESPONSE_PRICE_RUB:
            log.error(
                "ОТМЕНА: к оплате %s ₽ > потолка %s ₽ (MAX_RESPONSE_PRICE_RUB)",
                footer["to_pay"], config.MAX_RESPONSE_PRICE_RUB,
            )
            time.sleep(1.5)
            order_page.close(run_before_unload=False)
            return 1
        sent_today = store.sends_today()
        if sent_today >= config.DAILY_SEND_LIMIT:
            log.error(
                "ОТМЕНА: дневной лимит отправок (%d/%d, DAILY_SEND_LIMIT)",
                sent_today, config.DAILY_SEND_LIMIT,
            )
            time.sleep(1.5)
            order_page.close(run_before_unload=False)
            return 1

        log.warning("ОТПРАВЛЯЮ ПЛАТНЫЙ ОТКЛИК #%s (к оплате %s ₽)…", order_id, footer["to_pay"])
        outcome = respond_mod.click_send(order_page, ctx)
        shot2 = out_dir / f"{order_id}_{stamp}_after.png"
        order_page.screenshot(path=str(shot2), full_page=True)
        log.info("исход: url=%s rpc=%s", outcome.get("url_after"), outcome.get("rpc"))
        (out_dir / f"{order_id}_{stamp}_outcome.json").write_text(
            json.dumps({"footer": footer, "outcome": outcome}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # успех: редирект на чат заказа (r.php?id=<order>) — основной сигнал;
        # RPC-200 — дополнительный (ревью P1-3)
        ok = (f"r.php" in outcome.get("url_after", "")
              and f"id={order_id}" in outcome.get("url_after", "")) or bool(outcome.get("rpc"))
        store.set_send_status(order_id, "sent" if ok else "unknown")
        log.info("send_status=%s | скриншоты: %s, %s", "sent" if ok else "unknown", shot.name, shot2.name)
        return 0 if ok else 1
    finally:
        if order_page is not None:
            try:
                if not order_page.is_closed():
                    time.sleep(1.5)
                    order_page.close(run_before_unload=False)
            except Exception:
                pass
        bm.shutdown()
        store.close()


def run_fetch_details(order_id: str) -> int:
    """Открыть конкретный заказ и записать FullOrder в БД (для тестов/дозагрузки)."""
    bm = BrowserManager()
    store = store_mod.Store(config.DB_PATH)
    try:
        state = bm.start()
        if state == BROWSER_OFFLINE:
            return 1
        if state != "READY":
            log.error("сессия не READY: %s", state)
            return 2
        row = store.get_candidate(order_id)
        if row is None:
            store.ensure_candidate(order_id, None)
        result = load_details(bm, store, order_id)
        return 0 if result == "DETAILS_READY" else 1
    finally:
        bm.shutdown()
        store.close()


def run_cli(command: str, order_id: str | None) -> int:
    store = store_mod.Store(config.DB_PATH)
    try:
        if command == "candidates":
            rows = store.list_candidates()
            if not rows:
                print("кандидатов пока нет (появятся после подключения LLM-триажа)")
                return 0
            for r in rows:
                print(
                    f"#{r['order_id']} pr={r['priority']} det={r['details_status']} "
                    f"draft={r['draft_status']} send={r['send_status']} | {(r['title'] or '')[:50]}"
                )
            return 0
        if command in ("sent", "skip"):
            if not order_id:
                print(f"укажи order_id: main.py {command} <order_id>")
                return 2
            status = "sent" if command == "sent" else "skipped"
            if store.set_send_status(order_id, status):
                print(f"#{order_id} → send_status={status}")
                return 0
            print(f"кандидат #{order_id} не найден в БД")
            return 1
    finally:
        store.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Контур A: воркер откликов Профи.ру")
    parser.add_argument(
        "command", nargs="?", choices=["sent", "skip", "candidates", "fetch-details", "respond"]
    )
    parser.add_argument("order_id", nargs="?")
    parser.add_argument("--once", action="store_true", help="один цикл вместо бесконечного лупа")
    parser.add_argument("--cycles", type=int, default=None, help="остановиться после N циклов")
    parser.add_argument("--rate", type=int, default=None, help="ставка ₽/час для формы отклика")
    parser.add_argument("--text", default=None, help="кастомный текст отклика (первый ответ клиенту)")
    parser.add_argument(
        "--send", action="store_true",
        help="РЕАЛЬНО нажать «Откликнуться» (платно!); без флага — только заполнить форму",
    )
    args = parser.parse_args()

    setup_logging()

    if args.command:
        if args.command == "fetch-details":
            if not args.order_id:
                print("укажи order_id: main.py fetch-details <order_id>")
                return 2
            return run_fetch_details(args.order_id)
        if args.command == "respond":
            if not args.order_id or not args.rate or not args.text:
                print("usage: main.py respond <order_id> --rate 2500 --text '...' [--send]")
                return 2
            return run_respond(args.order_id, args.rate, args.text, send=args.send)
        return run_cli(args.command, args.order_id)
    if args.once:
        return run_once()
    return run_loop(args.cycles)


if __name__ == "__main__":
    sys.exit(main())
