# Остановить воркеры и автопилоты profi-agent на Windows (Chrome не трогаем).
# Все акки сразу; Chrome не трогаем.
$repo = Split-Path -Parent $PSScriptRoot
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='powershell.exe'" |
  Where-Object { $_.CommandLine -match "profi-worker-|profi-loop-|profi-autopilot-loop|-m profi" } |
  ForEach-Object {
    Write-Host "kill $($_.ProcessId): $($_.CommandLine.Substring(0, [Math]::Min(90, $_.CommandLine.Length)))"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }
Remove-Item (Join-Path $repo "data\autopilot.lock") -ErrorAction SilentlyContinue
Remove-Item (Join-Path $repo "data\*.autopilot.lock") -ErrorAction SilentlyContinue
Write-Host "остановлено"
