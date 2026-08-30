"""FeedCapture: reload ленты → capture-window → canonical BoSearchBoardItems → FeedSnapshot.

Спека: разд. 8 (контракт матчинга по operationName), 9 (корреляция с reload),
10 (capture-window и выбор canonical), 10.2 (validation), 11 (parsing),
2 (SNIPPET-поля). Несколько подходящих ответов с одинаковым содержимым —
не неоднозначность; с разным — FEED_AMBIGUOUS, не угадываем.
"""
from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import urlparse

from playwright.sync_api import Page, Response

import config
from models import FeedSnapshot, OrderSnippet

log = logging.getLogger("profi.feed")

OPERATION = "BoSearchBoardItems"


class FeedCaptureError(Exception):
    """Feed не пойман или невалиден (детали — в диагностике)."""


class FeedAmbiguous(FeedCaptureError):
    """Несколько canonical-ответов с разным содержимым — решение за человеком/логом."""


class FeedAuthError(FeedCaptureError):
    """GraphQL ответил 401/403 — сессия сломана или сработал антибот."""


_OP_RE = re.compile(r"\b(?:query|mutation)\s+([A-Za-z_][A-Za-z0-9_]*)")


def _operation_name(body) -> str | None:
    """Имя операции из тела запроса.

    Живой факт этого билда (2026-08-31): поля operationName в JSON нет,
    имя сидит в тексте query после #prfrtkn-комментария:
    {"query":"#prfrtkn:...\\n query BoSearchBoardItems($filter: ...)"}.
    Проверяем оба варианта на случай возврата поля.
    """
    if not isinstance(body, dict):
        return None
    op = body.get("operationName")
    if isinstance(op, str) and op:
        return op
    m = _OP_RE.search(body.get("query") or "")
    return m.group(1) if m else None


def _is_feed_request(response: Response) -> bool:
    """method == POST, path == /graphql, операция BoSearchBoardItems (по operationName или тексту query)."""
    try:
        req = response.request
        if req.method != "POST":
            return False
        if urlparse(req.url).path != "/graphql":
            return False
        return _operation_name(req.post_data_json) == OPERATION
    except Exception:
        return False


def _inspect(resp: Response) -> dict:
    """Диагностическая сводка по одному кандидату + его валидность (спека 10.2)."""
    info: dict = {
        "ts": time.time(),
        "status": None,
        "variables": None,
        "cursor_is_none": None,
        "valid": False,
        "items_count": None,
        "error": None,
    }
    try:
        info["status"] = resp.status
        req_body = resp.request.post_data_json or {}
        info["variables"] = req_body.get("variables")
        vars_ = info["variables"] or {}
        info["cursor_is_none"] = vars_.get("cursor") is None

        if resp.status in (401, 403):
            info["error"] = f"HTTP {resp.status}"
            return info
        if resp.status != 200:
            info["error"] = f"HTTP {resp.status}"
            return info

        payload = resp.json()
        bo = (payload.get("data") or {}).get("boSearchBoardItems")
        if not isinstance(bo, dict):
            info["error"] = "нет data.boSearchBoardItems"
            return info
        items = bo.get("items")
        if not isinstance(items, list):
            info["error"] = "items не массив"
            return info
        info["items_count"] = len(items)
        info["payload"] = payload
        info["valid"] = True
    except Exception as e:
        info["error"] = f"parse: {e}"
    return info


def _fingerprint(payload: dict):
    """Что отличает один canonical-ответ от другого (id + lastUpdate + total)."""
    bo = payload["data"]["boSearchBoardItems"]
    items = [
        (str(i.get("id")), i.get("lastUpdateDate"))
        for i in bo.get("items") or []
        if i.get("type") == "SNIPPET"
    ]
    return (bo.get("totalCount"), tuple(items))


def _snippet_from_item(item: dict) -> OrderSnippet:
    """Защитимое извлечение полей SNIPPET: отсутствие/смена формы поля не роняет цикл."""
    price = item.get("price")
    if isinstance(price, dict):
        price_raw = price.get("value")
    else:
        price_raw = price

    geo = item.get("geo") or {}
    remote = geo.get("remote")
    if isinstance(remote, dict):
        geo_remote = remote.get("prefix")
        geo_remote_suffix = remote.get("suffix")
    else:
        geo_remote, geo_remote_suffix = remote, None
    local = geo.get("local")
    geo_local = local if isinstance(local, str) else (local or {}).get("prefix") if isinstance(local, dict) else None

    badges_raw = item.get("badges") or []
    badges = [b.get("id") if isinstance(b, dict) else str(b) for b in badges_raw]

    client = item.get("clientInfo") or {}
    tags_raw = item.get("clientTags") or client.get("tags") or []
    client_tags = [t.get("id") if isinstance(t, dict) else str(t) for t in tags_raw]

    last_update = item.get("lastUpdateDate")
    if isinstance(last_update, str) and last_update.isdigit():
        last_update = int(last_update)
    elif isinstance(last_update, float):
        last_update = int(last_update)
    if not isinstance(last_update, int):
        last_update = None

    score = item.get("score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None

    return OrderSnippet(
        id=str(item.get("id")),
        title=item.get("title") or "",
        description=item.get("description") or "",
        price_raw=price_raw,
        last_update=last_update,
        score=score,
        is_fresh=bool(item.get("isFresh")),
        is_viewed=bool(item.get("isViewed")),
        is_reposted=bool(item.get("isReposted")),
        badges=badges,
        client_name=client.get("name"),
        client_tags=client_tags,
        schedule=item.get("schedule"),
        geo_remote=geo_remote,
        geo_remote_suffix=geo_remote_suffix,
        geo_local=geo_local,
        raw=item,
    )


def normalize(payload: dict) -> FeedSnapshot:
    bo = payload["data"]["boSearchBoardItems"]
    snippets = []
    for item in bo.get("items") or []:
        try:
            if item.get("type") != "SNIPPET":
                continue  # STORIES / CAROUSEL — игнор; DIVIDER — мета, пока не нужен
            snippets.append(_snippet_from_item(item))
        except Exception:
            log.exception("не смог нормализовать item: %r", str(item)[:200])
    return FeedSnapshot(
        snippets=snippets,
        total_count=bo.get("totalCount"),
        next_cursor=bo.get("nextCursor"),
        server_ts=bo.get("serverTs"),
        raw=payload,
    )


class FeedCapture:
    def __init__(self, page: Page):
        self.page = page
        self.last_diag: list[dict] = []

    def reload_and_capture(self) -> FeedSnapshot:
        """Listener ставится ДО reload (спека разд. 9). Собираем все совпадения за окно."""
        candidates: list[Response] = []

        def on_response(resp: Response) -> None:
            if _is_feed_request(resp):
                candidates.append(resp)

        self.page.on("response", on_response)
        try:
            self.page.reload(wait_until="domcontentloaded", timeout=45_000)

            deadline = time.monotonic() + config.CAPTURE_WINDOW_S
            while time.monotonic() < deadline and not candidates:
                self.page.wait_for_timeout(200)
            # добираем повторы, чтобы видеть реальное число запросов за один reload
            self.page.wait_for_timeout(int(config.CAPTURE_EXTRA_S * 1000))
        finally:
            try:
                self.page.remove_listener("response", on_response)
            except Exception:
                pass

        if not candidates:
            raise FeedCaptureError(
                f"{OPERATION} не пойман за {config.CAPTURE_WINDOW_S} с после reload "
                f"(url сейчас: {self.page.url})"
            )

        parsed = [_inspect(r) for r in candidates]
        self.last_diag = [{k: v for k, v in p.items() if k != "payload"} for p in parsed]
        log.info("capture: %d ответ(ов) %s за окно: %s", len(parsed), OPERATION, self.last_diag)

        auth_hits = [p for p in parsed if p["status"] in (401, 403)]
        if auth_hits and not any(p["valid"] for p in parsed):
            raise FeedAuthError(f"graphql ответил {auth_hits[0]['status']} — сессия/антибот")

        valid = [p for p in parsed if p["valid"]]
        if not valid:
            raise FeedCaptureError(f"все {len(parsed)} ответов невалидны: {self.last_diag}")

        canonical = [p for p in valid if p["cursor_is_none"]]
        if not canonical:
            raise FeedCaptureError(f"нет ответа с cursor == null: {self.last_diag}")

        if len(canonical) > 1:
            fps = {_fingerprint(p["payload"]) for p in canonical}
            if len(fps) > 1:
                raise FeedAmbiguous(
                    f"{len(canonical)} canonical-ответов с разным содержимым — не угадываю"
                )
            log.info("canonical-ответов %d, содержимое идентично — беру последний", len(canonical))

        chosen = canonical[-1]
        return normalize(chosen["payload"])
