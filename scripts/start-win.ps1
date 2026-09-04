# Start one self-healing Windows supervisor for an account.
# Usage: powershell -File scripts\start-win.ps1 -Account info
# Stop:  powershell -File scripts\stop-win.ps1 -Account info
param([Parameter(Mandatory = $true)][string]$Account)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$envf = Join-Path $repo "accounts\$Account.env"
$supervisor = Join-Path $repo "scripts\account\supervise-win.ps1"

if (-not (Test-Path $envf)) {
    Write-Error "account env not found: $envf"
    exit 1
}
if (-not (Test-Path $supervisor)) {
    Write-Error "supervisor not found: $supervisor"
    exit 1
}

function Test-AccountToken([string]$CommandLine, [string]$Flag) {
    if (-not $CommandLine) { return $false }
    $pattern = [regex]::Escape($Flag) + '\s+"?' + [regex]::Escape($Account) + '"?(?:\s|$)'
    return [regex]::IsMatch($CommandLine, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
}

$processes = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue)
$existing = @($processes | Where-Object {
    $cmd = [string]$_.CommandLine
    $cmd -and
    $cmd.IndexOf("supervise-win.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
    (Test-AccountToken $cmd "-Account")
})
if ($existing.Count -gt 0) {
    Write-Host "[$Account] supervisor already running (pid $($existing[0].ProcessId))"
    exit 0
}

# Migration guard: the old launcher used temp wrappers and untagged Python.
# Starting the new supervisor on top of those could duplicate feed reloads/sends.
$legacy = @($processes | Where-Object {
    $cmd = [string]$_.CommandLine
    if (-not $cmd) { return $false }
    if ($cmd.IndexOf("profi-worker-$Account.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
    if ($cmd.IndexOf("profi-loop-$Account.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
    if (($cmd.IndexOf(" -m profi", [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -and
        ($cmd.IndexOf("--rhythm-tag", [System.StringComparison]::OrdinalIgnoreCase) -lt 0)) { return $true }
    return $false
})
if ($legacy.Count -gt 0) {
    Write-Error "legacy Windows worker/autopilot process detected. Run scripts\stop-win.ps1 once, then start again."
    exit 2
}

Start-Process -FilePath "powershell" -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$supervisor`"", "-Account", $Account
) -WindowStyle Hidden -WorkingDirectory $repo | Out-Null

Write-Host "[$Account] supervisor started; it owns Chrome health + worker health"
Write-Host "log: logs\supervisor-$Account.log"
