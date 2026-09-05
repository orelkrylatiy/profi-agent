from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "account" / "run-worker-win.ps1"


def test_worker_runner_switches_to_continue_before_native_python_call():
    text = RUNNER.read_text(encoding="utf-8-sig")
    continue_pos = text.index('$ErrorActionPreference = "Continue"')
    python_pos = text.index("& $python -m profi.main")
    assert continue_pos < python_pos
    assert "*>>" in text[python_pos:]


def _decode_powershell_redirect(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Windows PowerShell 5.1 can write native redirected output as UTF-16LE
        # even when no BOM survived the first write.
        return raw.decode("utf-16-le")


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell runtime semantics")
def test_powershell_51_native_stderr_redirection_is_non_terminating(tmp_path):
    powershell = shutil.which("powershell")
    python = shutil.which("python")
    if powershell is None or python is None:
        pytest.skip("Windows PowerShell/python unavailable")

    log = tmp_path / "native-stderr.log"
    command = (
        '$ErrorActionPreference = "Stop"; '
        '$ErrorActionPreference = "Continue"; '
        f'& "{python}" -c "import sys,time; '
        "sys.stderr.write('STDERR_SENTINEL\\n'); sys.stderr.flush(); "
        "time.sleep(0.1); print('STDOUT_SENTINEL')\" "
        f'*>> "{log}"; '
        "$code=$LASTEXITCODE; "
        "if ($code -ne 0) { exit $code }; exit 0"
    )
    proc = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    text = _decode_powershell_redirect(log)
    assert "STDERR_SENTINEL" in text
    assert "STDOUT_SENTINEL" in text
