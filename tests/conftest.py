from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_account_capability_state(tmp_path, monkeypatch):
    """Production capability is persistent; tests must never share its state."""
    from profi import capability

    path = tmp_path / "account.capability.json"
    monkeypatch.setattr(capability, "state_path", lambda db_path=None: path)
