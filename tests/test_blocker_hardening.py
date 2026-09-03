"""Regression tests for production blockers found in the 2026-09-03 review."""

from __future__ import annotations

import os
import subprocess
import sys

from profi.integration.orders import _payload_order_id


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


def test_payload_order_id_binds_order_screen_to_candidate():
    assert _payload_order_id(_order_payload("93400001")) == "93400001"
    assert _payload_order_id({"data": {"orders": []}}) is None
    assert _payload_order_id({}) is None


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
