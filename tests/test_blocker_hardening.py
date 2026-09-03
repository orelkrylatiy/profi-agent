"""Regression tests for production blockers found in the 2026-09-03 review."""

from __future__ import annotations

import os
import subprocess
import sys

from profi.browser import BROWSER_OFFLINE, BrowserManager
from profi.integration.orders import _payload_order_id, _responses_for_order


def _order_payload(order_id: str) -> dict:
    return {
        "data": {
            "orders": [
                {
                    "_id": order_id,
                    "boOrderScreen": {"id": order_id},
                }
            ]
        }
    }


class _FakeResponse:
    def __init__(self, order_id: str):
        self.order_id = order_id

    def json(self) -> dict:
        return _order_payload(self.order_id)


def test_payload_order_id_binds_order_screen_to_candidate():
    assert _payload_order_id(_order_payload("93400001")) == "93400001"
    assert _payload_order_id({"data": {"orders": []}}) is None
    assert _payload_order_id({}) is None


def test_context_listener_discards_other_orders():
    responses = [_FakeResponse("111"), _FakeResponse("222"), _FakeResponse("333")]
    matched = _responses_for_order(responses, "222")
    assert len(matched) == 1
    assert matched[0].order_id == "222"


def test_dead_browser_connection_triggers_reconnect(monkeypatch):
    class DeadBrowser:
        def is_connected(self):
            return False

    bm = BrowserManager()
    bm.browser = DeadBrowser()
    calls = []

    def reconnect():
        calls.append(True)
        return BROWSER_OFFLINE

    monkeypatch.setattr(bm, "reconnect", reconnect)
    assert bm.ensure_ready() == BROWSER_OFFLINE
    assert calls == [True]


def test_invalid_respond_mode_fails_closed():
    env = os.environ.copy()
    env["PROFI_RESPOND_MODE"] = "commision"  # realistic typo: missing second 's'
    proc = subprocess.run(
        [sys.executable, "-c", "import profi.config"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "невалидный PROFI_RESPOND_MODE" in (proc.stderr + proc.stdout)


def test_valid_respond_modes_still_import():
    for mode in ("pay", "commission"):
        env = os.environ.copy()
        env["PROFI_RESPOND_MODE"] = mode
        proc = subprocess.run(
            [sys.executable, "-c", "import profi.config; print(profi.config.RESPOND_MODE)"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == mode
