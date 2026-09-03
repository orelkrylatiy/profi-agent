# Запуск воркера + автопилота profi-agent на Windows для ОДНОГО акка.
# Использование: powershell -File scripts\start-win.ps1 -Account info   (или lang)
# Chrome акка уже должен быть запущен с CDP (профиль/порт/персона/тариф — accounts\<акк>.env).
# Стоп: scripts\stop-win.ps1
param([Parameter(Mandatory = $true)][string]$Account)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$envf = Join-Path $repo "accounts\$Account.env"
if (-not (Test-Path $envf)) { Write-Host "нет файла $envf"; exit 1 }

$srcEnv = @"
Set-Location "$repo"
`$env:PYTHONUTF8 = "1"
`$env:PYTHONPATH = "$repo\src"
`$env:PROFI_CHROME_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
Get-Content "$envf" -Encoding UTF8 | ForEach-Object {
  if (`$_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
    Set-Item -Path ("env:" + `$Matches[1]) -Value `$Matches[2]
  }
}
"@

# воркер (лента + чат-чек) — решения пишет сам в logs\worker-<акк>.log
$workerScript = $srcEnv + @"

& "$repo\.venv\Scripts\python.exe" -m profi *>> "$repo\logs\console-$Account.log"
"@
$workerPs = Join-Path $env:TEMP "profi-worker-$Account.ps1"
$workerScript | Out-File -FilePath $workerPs -Encoding utf8
Start-Process -FilePath "powershell" -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $workerPs `
  -WindowStyle Hidden -WorkingDirectory $repo

# автопилот (каждые 120 с: гейты -> LLM -> отправка) — решения в logs\autopilot-<акк>.log
$loopScript = $srcEnv + @"

while (`$true) {
  & "$repo\.venv\Scripts\python.exe" -m profi autopilot *>> "$repo\logs\loop-$Account.log"
  Start-Sleep -Seconds 120
}
"@
$loopPs = Join-Path $env:TEMP "profi-loop-$Account.ps1"
$loopScript | Out-File -FilePath $loopPs -Encoding utf8
Start-Process -FilePath "powershell" -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $loopPs `
  -WindowStyle Hidden -WorkingDirectory $repo

Write-Host "стартовано [$Account]: воркер + автопилот (логи: logs\worker-$Account.log, logs\autopilot-$Account.log)"
