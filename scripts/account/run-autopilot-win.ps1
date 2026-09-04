param([Parameter(Mandatory = $true)][string]$Account)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$envf = Join-Path $repo "accounts\$Account.env"
if (-not (Test-Path $envf)) {
    Write-Error "account env not found: $envf"
    exit 1
}

function Import-ProfiEnv([string]$Path) {
    Get-Content $Path -Encoding UTF8 | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
            $name = $Matches[1]
            $value = $Matches[2].Trim()
            if ($value.Length -ge 2) {
                if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                    ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }
            Set-Item -Path ("env:" + $name) -Value $value
        }
    }
}

Set-Location $repo
Import-ProfiEnv $envf
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = Join-Path $repo "src"
$env:PROFI_CHROME_NO_LAUNCH = "1"
$env:PROFI_RHYTHM_TAG = $Account

$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "python venv not found: $python"
    exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $repo "logs") | Out-Null
# EAP="Continue": см. комментарий в run-worker-win.ps1 — stderr-строки python
# при *>> становятся ErrorRecord, и с EAP="Stop" wrapper умирал молча.
$ErrorActionPreference = "Continue"
while ($true) {
    & $python -m profi.main autopilot --rhythm-tag $Account *>> (Join-Path $repo "logs\autopilot-$Account.log")
    Start-Sleep -Seconds 120
}
