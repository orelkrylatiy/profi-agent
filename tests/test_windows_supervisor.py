from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "scripts" / "start-win.ps1"
STOP = ROOT / "scripts" / "stop-win.ps1"
SUPERVISOR = ROOT / "scripts" / "account" / "supervise-win.ps1"
WORKER = ROOT / "scripts" / "account" / "run-worker-win.ps1"
AUTOPILOT = ROOT / "scripts" / "account" / "run-autopilot-win.ps1"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_start_win_is_idempotent_and_starts_single_account_supervisor():
    text = _text(START)
    assert "supervise-win.ps1" in text
    assert "Get-CimInstance Win32_Process" in text
    assert "already" in text.lower() or "уже" in text.lower()
    assert "run-autopilot-win.ps1" not in text
    assert "while ($true)" not in text


def test_supervisor_has_process_lifetime_singleton_guard():
    text = _text(SUPERVISOR)
    assert "System.Threading.Mutex" in text
    assert "SUPERVISOR_DUPLICATE" in text


def test_supervisor_owns_browser_lifecycle_but_worker_keeps_no_launch():
    text = _text(SUPERVISOR)
    assert "/json/version" in text
    assert "--remote-debugging-port=" in text
    assert "--user-data-dir=" in text
    assert "PROFI_CHROME_NO_LAUNCH" in text
    assert '"1"' in text or "='1'" in text or '= "1"' in text


def test_cdp_health_is_bound_to_expected_profile_and_port():
    text = _text(SUPERVISOR)
    ensure = text[text.index("function Ensure-Browser") : text.index("function Test-AccountToken")]
    assert "$cdpUp = Test-Cdp" in ensure
    assert "$profileProcesses = @(Get-ProfileChromeProcesses)" in ensure
    assert "CDP_PORT_CONFLICT" in ensure
    assert ensure.index("$profileProcesses = @(Get-ProfileChromeProcesses)") < ensure.index(
        "if ($cdpUp)"
    )
    # A listening CDP port is READY only when the same process set contains our
    # expected user-data-dir + remote-debugging-port pair.
    assert "$managed.Count -gt 0" in ensure


def test_supervisor_never_kills_foreign_profile_owner():
    text = _text(SUPERVISOR)
    assert "PROFILE_IN_USE_NO_CDP" in text
    assert "managed" in text.lower()
    assert "Stop-Process" in text
    # A matching managed profile+port may be recycled, but a foreign owner of
    # the same user-data-dir must fail closed instead of being killed.
    assert "foreign" in text.lower()


def test_supervisor_waits_for_cdp_before_starting_worker_and_restarts_worker():
    text = _text(SUPERVISOR)
    browser_pos = text.index("Ensure-Browser")
    worker_pos = text.index("Ensure-Worker")
    assert browser_pos < worker_pos
    assert "Start-Sleep" in text
    assert "run-worker-win.ps1" in text


def test_legacy_autopilot_only_runs_when_fast_path_is_disabled():
    text = _text(SUPERVISOR)
    assert "PROFI_FAST_PATH" in text
    assert "run-autopilot-win.ps1" in text
    assert "Stop-LegacyAutopilot" in text


def test_autopilot_detection_includes_orphan_python_child():
    text = _text(SUPERVISOR)
    section = text[
        text.index("function Get-AutopilotRunnerProcesses") : text.index(
            "function Stop-LegacyAutopilot"
        )
    ]
    assert "python.exe" in section
    assert "profi.main" in section
    assert "autopilot" in section
    assert "--rhythm-tag" in section


def test_stop_win_can_target_one_account_and_stops_supervisor_children_not_chrome():
    text = _text(STOP)
    assert "param(" in text
    assert "$Account" in text
    assert "supervise-win.ps1" in text
    assert "run-worker-win.ps1" in text
    assert "run-autopilot-win.ps1" in text
    assert "chrome.exe" not in text.lower()


def test_worker_runner_tags_process_with_account_and_loads_account_env():
    text = _text(WORKER)
    assert "accounts\\$Account.env" in text
    assert "--rhythm-tag" in text
    assert "PYTHONPATH" in text
    assert "PYTHONUTF8" in text


def test_autopilot_runner_is_legacy_loop_with_account_env():
    text = _text(AUTOPILOT)
    assert "accounts\\$Account.env" in text
    assert "autopilot" in text
    assert "Start-Sleep -Seconds 120" in text


def test_powershell_scripts_parse_in_all_available_shells():
    shells = []
    for name in ("powershell", "pwsh"):
        resolved = shutil.which(name)
        if resolved and resolved not in shells:
            shells.append(resolved)
    if not shells:
        return

    for shell in shells:
        for path in (START, STOP, SUPERVISOR, WORKER, AUTOPILOT):
            command = (
                "$tokens=$null; $errors=$null; "
                f"[System.Management.Automation.Language.Parser]::ParseFile('{path.as_posix()}',"
                "[ref]$tokens,[ref]$errors) > $null; "
                "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
            )
            subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", command],
                check=True,
                cwd=ROOT,
            )


def test_windows_runtime_port_conflict_singleton_and_targeted_stop():
    if os.name != "nt":
        return
    powershell = shutil.which("powershell")
    if powershell is None:
        return

    class OkHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, _format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), OkHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    account = "ci-supervisor-runtime"
    env_path = ROOT / "accounts" / f"{account}.env"
    log_path = ROOT / "logs" / f"supervisor-{account}.log"
    env_path.write_text(
        f"PROFI_CDP_PORT={port}\n"
        f"PROFI_CHROME_PROFILE=data/browser-profiles/{account}\n"
        "PROFI_BROWSER_WATCH_INTERVAL=3\n",
        encoding="utf-8",
    )
    log_path.unlink(missing_ok=True)

    first = None
    try:
        first = subprocess.Popen(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SUPERVISOR),
                "-Account",
                account,
            ],
            cwd=ROOT,
        )

        deadline = time.monotonic() + 10
        log = ""
        while time.monotonic() < deadline:
            if log_path.exists():
                log = log_path.read_text(encoding="utf-8-sig")
                if "CDP_PORT_CONFLICT" in log:
                    break
            time.sleep(0.2)
        assert first.poll() is None
        assert "CDP_PORT_CONFLICT" in log
        assert "WORKER_START" not in log

        second = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SUPERVISOR),
                "-Account",
                account,
            ],
            cwd=ROOT,
            timeout=10,
            check=False,
        )
        assert second.returncode == 0

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            log = log_path.read_text(encoding="utf-8-sig")
            if "SUPERVISOR_DUPLICATE" in log:
                break
            time.sleep(0.1)
        assert "SUPERVISOR_DUPLICATE" in log

        subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(STOP),
                "-Account",
                account,
            ],
            cwd=ROOT,
            timeout=15,
            check=True,
        )
        first.wait(timeout=10)
    finally:
        if first is not None and first.poll() is None:
            first.terminate()
            try:
                first.wait(timeout=5)
            except subprocess.TimeoutExpired:
                first.kill()
        server.shutdown()
        server.server_close()
        env_path.unlink(missing_ok=True)
        log_path.unlink(missing_ok=True)
