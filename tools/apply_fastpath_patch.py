"""One-shot branch helper: apply narrow fast-path edits to the large legacy main.py.

This file is removed before the PR is finalized. It exists only because the GitHub
contents API replaces whole files and the integration changes are intentionally
small/string-auditable.
"""

from pathlib import Path

PATH = Path("src/profi/main.py")
text = PATH.read_text(encoding="utf-8")

old_load = '''def load_details(bm: BrowserManager, store: Store, order_id: str) -> str:
    """Открыть заказ → BoOrderScreen → FullOrder → UPDATE candidates (спека §19-22).

    Одна order-вкладка за раз, закрывается после обработки.
    """
    try:
        human_pause()
        ctx = bm.context()
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
'''

new_load = '''def load_details(
    bm: BrowserManager, store: Store, order_id: str, *, fast_path: bool = False
) -> str:
    """Открыть заказ → FullOrder; worker fast-path решает/отправляет в той же вкладке.

    Одна order-вкладка за раз. В fast-path details + draft claim пишутся атомарно,
    поэтому legacy-autopilot не может переоткрыть свежий заказ параллельно.
    Вкладка всегда закрывается здесь, после решения/отправки.
    """
    try:
        human_pause()
        ctx = bm.context()
        order_page, captured = open_candidate(ctx, bm.page, order_id)
    except OrderOpenError as e:
        log.error("открытие #%s не удалось: %s", order_id, e)
        store.update_details(order_id, "error", None)
        if fast_path:
            store.set_draft(order_id, "error", error=f"open-fail: {str(e)[:200]}")
            store.set_send_status(order_id, "failed")
            store.set_note(order_id, "fast-path: карточка не открылась, без фонового повтора")
        return "DETAILS_ERROR"

    try:
        dom = extract_dom_texts(order_page)
        if not captured:
            raise OrderOpenError("BoOrderScreen не пойман в новой вкладке")
        full = extract_full_order(captured[0].json(), dom.get("container_text"))
    except Exception as e:
        log.error("извлечение деталей #%s упало: %s", order_id, e)
        store.update_details(order_id, "error", None)
        if fast_path:
            store.set_draft(order_id, "error", error=f"details: {str(e)[:200]}")
            store.set_send_status(order_id, "failed")
        return "DETAILS_ERROR"

    try:
        payload = json.dumps(full, ensure_ascii=False)
        if fast_path:
            store.update_details_for_fast_path(order_id, payload)
        else:
            store.update_details(order_id, "ready", payload)
        log.info(
            "#%s: детали готовы | отклик %s ₽ | тариф %s | позиция %s | клиент %s",
            order_id,
            full.get("bid_price"),
            full.get("tariff_default"),
            full.get("competition_position"),
            full.get("client_block_dom", {}).get("name"),
        )

        if fast_path:
            from profi.fastpath import process_open_candidate

            user_prompt = _llm_order_payload(full) + "\\n\\n" + _recipient_hint(full)
            result = process_open_candidate(
                order_page,
                ctx,
                store,
                order_id,
                full,
                system_prompt_factory=lambda: TRIAGE_SYSTEM + _style_variation(),
                user_prompt=user_prompt,
                llm_blocked=_llm_cooldown_until() > time.time(),
                on_limit=_llm_cooldown_set,
            )
            log.info("#%s: fast-path → %s", order_id, result)
        return "DETAILS_READY"
    except Exception as e:
        # Details уже сохранены. Не превращаем успешный parsing в details_error,
        # если сломался новый decision/send layer; кандидат становится terminal.
        log.exception("fast-path #%s упал: %s", order_id, e)
        if fast_path:
            store.set_draft(order_id, "error", error=f"fast-path: {str(e)[:200]}")
            store.set_send_status(order_id, "failed")
            store.set_note(order_id, "fast-path: неожиданный сбой, без фонового повтора")
            return "DETAILS_READY"
        raise
    finally:
        try:
            time.sleep(1.5)
            order_page.close(run_before_unload=False)
        except Exception:
            pass
'''

old_call = '''                if config.AUTO_LOAD_DETAILS:
                    load_details(bm, store, s.id)
'''
new_call = '''                if config.AUTO_LOAD_DETAILS:
                    load_details(bm, store, s.id, fast_path=config.FAST_PATH_ENABLED)
'''

old_cooldown = '''            cooldown_until = _llm_cooldown_until()
            if cooldown_until > time.time():
                # LLM у провайдера на лимите: в Profi не заходим вовсе (лента
                # не перезагружается, чаты молчат) — по образцу нерабочих часов
                log.info(
                    "LLM на лимите до %s — воркер спит (проверка раз в 10 мин)",
                    datetime.fromtimestamp(cooldown_until).strftime("%H:%M"),
                )
                time.sleep(10 * 60)
                continue
'''
new_cooldown = '''            # LLM cooldown больше не останавливает acquisition: fresh-order
            # fast-path использует profile fallback. Чаты и legacy-autopilot
            # по-прежнему уважают cooldown и не тратят LLM-квоту.
'''

old_open_fail = '''                    except OrderOpenError as e:
                        # Карточка не открылась (goto-таймаут/исчезла): НЕ скипаем —
                        # зависания страниц бывают транзиентными (03.09: свежие
                        # заказы открывались через попытку). Кандидат остаётся
                        # pending и будет повторён следующим проходом; трупов
                        # выше 2.5 ч снимет булк-скип.
                        store.set_note(order_id, f"не открылась, повторим: {str(e)[:120]}")
                        store.conn.execute(
                            "UPDATE candidates SET last_error=?, updated_at=? WHERE order_id=?",
                            (f"open-fail: {str(e)[:200]}", int(time.time()), order_id),
                        )
                        store.conn.commit()
                        log.warning(
                            "#%s: не открылась — остаётся в очереди (%s)", order_id, str(e)[:80]
                        )
                        with open(config.AUTOPILOT_LOG, "a", encoding="utf-8") as f:
                            f.write(
                                f"{now:%Y-%m-%d %H:%M} #{order_id} OPEN_FAIL: повтор следующего прохода\\n"
                            )
                        send_failed = True
                        sent = None
'''
new_open_fail = '''                    except OrderOpenError as e:
                        # Background reopen больше не делаем: freshness важнее
                        # completeness. Сам open_candidate уже имеет один
                        # immediate technical retry для direct URL.
                        from profi.fastpath import mark_terminal_open_failure

                        mark_terminal_open_failure(store, order_id, e)
                        log.warning(
                            "#%s: не открылась — terminal failed, без следующего прохода (%s)",
                            order_id,
                            str(e)[:80],
                        )
                        with open(config.AUTOPILOT_LOG, "a", encoding="utf-8") as f:
                            f.write(
                                f"{now:%Y-%m-%d %H:%M} #{order_id} OPEN_FAIL: terminal, no retry\\n"
                            )
                        send_failed = True
                        sent = None
'''

replacements = [
    (old_load, new_load, "load_details"),
    (old_call, new_call, "run_cycle fast-path call"),
    (old_cooldown, new_cooldown, "worker LLM cooldown"),
    (old_open_fail, new_open_fail, "legacy OPEN_FAIL terminal"),
]

for old, new, label in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    text = text.replace(old, new)

PATH.write_text(text, encoding="utf-8")
print("fast-path integration patch applied")
