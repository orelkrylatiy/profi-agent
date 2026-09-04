param([Parameter(Mandatory = $true)][string]$Account)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$envf = Join-Path $repo "accounts\$Account.env"
$logDir = Join-Path $repo "logs"
$logFile = Join-Path $logDir "supervisor-$Account.log"

if (-not (Test-Path $envf)) {
    Write-Error "account env not found: $envf"
    exit 1
}
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

# The launcher is idempotent, but direct/concurrent supervisor starts must also
# be safe. A process-lifetime named mutex closes the last race between two
# start-win invocations that both inspect the process table at the same time.
$safeAccount = [regex]::Replace($Account, '[^A-Za-z0-9_.-]', '_')
$mutexName = "Local\ProfiAgentSupervisor_$safeAccount"
$createdNew = $false
$script:supervisorMutex = [System.Threading.Mutex]::new($true, $mutexName, [ref]$createdNew)
if (-not $createdNew) {
    Write-Log "SUPERVISOR_DUPLICATE account=$Account — another owner already holds $mutexName"
    $script:supervisorMutex.Dispose()
    exit 0
}

$script:lastIssue = ""
function Write-IssueOnce([string]$Code, [string]$Message) {
    if ($script:lastIssue -ne $Code) {
        Write-Log "$Code $Message"
        $script:lastIssue = $Code
    }
}

function Clear-Issue {
    $script:lastIssue = ""
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

Import-ProfiEnv $envf
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = Join-Path $repo "src"
# Browser ownership belongs to this supervisor. BrowserManager only connects/reconnects.
$env:PROFI_CHROME_NO_LAUNCH = "1"
$env:PROFI_RHYTHM_TAG = $Account

if (-not $env:PROFI_CDP_PORT) {
    Write-Error "PROFI_CDP_PORT is required in $envf"
    exit 1
}
if (-not $env:PROFI_CHROME_PROFILE) {
    Write-Error "PROFI_CHROME_PROFILE is required in $envf"
    exit 1
}

$port = [int]$env:PROFI_CDP_PORT
if ([System.IO.Path]::IsPathRooted($env:PROFI_CHROME_PROFILE)) {
    $profile = [System.IO.Path]::GetFullPath($env:PROFI_CHROME_PROFILE)
} else {
    $profile = [System.IO.Path]::GetFullPath((Join-Path $repo $env:PROFI_CHROME_PROFILE))
}
$watchInterval = 10
if ($env:PROFI_BROWSER_WATCH_INTERVAL) {
    $watchInterval = [Math]::Max(3, [int]$env:PROFI_BROWSER_WATCH_INTERVAL)
}
$restartFailures = 3
if ($env:PROFI_BROWSER_RESTART_FAILURES) {
    $restartFailures = [Math]::Max(2, [int]$env:PROFI_BROWSER_RESTART_FAILURES)
}

function Resolve-ChromePath {
    $candidates = @()
    if ($env:PROFI_CHROME_PATH) {
        $candidates += $env:PROFI_CHROME_PATH
    }
    if ($env:ProgramFiles) {
        $candidates += (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe")
    }
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe")
    }
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate -PathType Leaf)) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "Chrome executable not found; set PROFI_CHROME_PATH"
}

function Test-Cdp {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/json/version" -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Get-ProfileChromeProcesses {
    $result = @()
    $all = @(Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue)
    foreach ($proc in $all) {
        $cmd = [string]$proc.CommandLine
        if (-not $cmd) { continue }
        if ($cmd.IndexOf("--user-data-dir", [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
            continue
        }
        if ($cmd.IndexOf($profile, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $result += $proc
        }
    }
    return @($result)
}

function Get-ManagedChromeProcesses {
    return @(Get-ProfileChromeProcesses | Where-Object {
        ([string]$_.CommandLine).IndexOf("--remote-debugging-port=$port", [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    })
}

function Test-ExpectedCdp {
    if (-not (Test-Cdp)) { return $false }
    return @(Get-ManagedChromeProcesses).Count -gt 0
}

function Start-ManagedBrowser {
    $chrome = Resolve-ChromePath
    New-Item -ItemType Directory -Force -Path $profile | Out-Null
    $args = @(
        "--user-data-dir=`"$profile`"",
        "--remote-debugging-port=$port",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank"
    )
    Write-Log "BROWSER_START profile=$profile port=$port exe=$chrome"
    $proc = Start-Process -FilePath $chrome -ArgumentList $args -WindowStyle Minimized -PassThru
    $deadline = (Get-Date).AddSeconds(25)
    while ((Get-Date) -lt $deadline) {
        if (Test-ExpectedCdp) {
            Write-Log "BROWSER_READY pid=$($proc.Id) port=$port"
            Clear-Issue
            return $true
        }
        if ($proc.HasExited) {
            Write-Log "BROWSER_EXIT_EARLY pid=$($proc.Id) code=$($proc.ExitCode)"
            return $false
        }
        Start-Sleep -Milliseconds 700
    }
    Write-Log "BROWSER_START_TIMEOUT pid=$($proc.Id) port=$port"
    return $false
}

function Ensure-Browser {
    param([ref]$FailureCount)

    # Never trust a listening port by itself: another account/browser can own
    # the same port. READY requires both the CDP endpoint and a Chrome process
    # with this account's exact user-data-dir + remote-debugging-port.
    $cdpUp = Test-Cdp
    $profileProcesses = @(Get-ProfileChromeProcesses)
    $managed = @($profileProcesses | Where-Object {
        ([string]$_.CommandLine).IndexOf("--remote-debugging-port=$port", [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    })
    $foreign = @($profileProcesses | Where-Object {
        ([string]$_.CommandLine).IndexOf("--remote-debugging-port=$port", [System.StringComparison]::OrdinalIgnoreCase) -lt 0
    })

    if ($cdpUp) {
        $FailureCount.Value = 0
        if ($managed.Count -gt 0) {
            Clear-Issue
            return $true
        }
        Write-IssueOnce "CDP_PORT_CONFLICT" "port=$port responds but expected profile=$profile is not its managed owner; waiting"
        return $false
    }

    # If the same profile is already owned by another Chrome without our CDP port,
    # fail closed. Never kill a user's/foreign profile owner automatically.
    if ($managed.Count -eq 0 -and $foreign.Count -gt 0) {
        $FailureCount.Value = 0
        Write-IssueOnce "PROFILE_IN_USE_NO_CDP" "foreign Chrome owns profile=$profile; waiting, not killing it"
        return $false
    }

    if ($managed.Count -gt 0) {
        $FailureCount.Value = $FailureCount.Value + 1
        if ($FailureCount.Value -lt $restartFailures) {
            Write-IssueOnce "CDP_UNHEALTHY" "managed Chrome exists but CDP is down; failure=$($FailureCount.Value)/$restartFailures"
            return $false
        }
        Write-Log "BROWSER_RECYCLE managed Chrome failed CDP $($FailureCount.Value) times"
        foreach ($proc in $managed) {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
        $FailureCount.Value = 0
        return Start-ManagedBrowser
    }

    $FailureCount.Value = 0
    return Start-ManagedBrowser
}

function Test-AccountToken([string]$CommandLine, [string]$Flag) {
    if (-not $CommandLine) { return $false }
    $pattern = [regex]::Escape($Flag) + '\s+"?' + [regex]::Escape($Account) + '"?(?:\s|$)'
    return [regex]::IsMatch($CommandLine, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
}

function Test-WorkerRunning {
    $processes = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue)
    foreach ($proc in $processes) {
        $cmd = [string]$proc.CommandLine
        if (-not $cmd) { continue }
        if ($cmd.IndexOf("run-worker-win.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            (Test-AccountToken $cmd "-Account")) {
            return $true
        }
        if ($cmd.IndexOf("profi.main", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            (Test-AccountToken $cmd "--rhythm-tag")) {
            return $true
        }
    }
    return $false
}

$script:lastWorkerStart = [datetime]::MinValue
function Ensure-Worker {
    param([bool]$BrowserReady)

    if (-not $BrowserReady) { return }
    if (Test-WorkerRunning) { return }
    if (((Get-Date) - $script:lastWorkerStart).TotalSeconds -lt 30) { return }

    $runner = Join-Path $repo "scripts\account\run-worker-win.ps1"
    Write-Log "WORKER_START account=$Account"
    Start-Process -FilePath "powershell" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$runner`"", "-Account", $Account
    ) -WindowStyle Hidden -WorkingDirectory $repo | Out-Null
    $script:lastWorkerStart = Get-Date
}

function Get-AutopilotRunnerProcesses {
    $result = @()
    $processes = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue)
    foreach ($proc in $processes) {
        $cmd = [string]$proc.CommandLine
        if (-not $cmd) { continue }
        $newRunner = $cmd.IndexOf("run-autopilot-win.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and (Test-AccountToken $cmd "-Account")
        $legacyRunner = $cmd.IndexOf("profi-loop-$Account.ps1", [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        $pythonChild = $cmd.IndexOf("profi.main", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $cmd.IndexOf("autopilot", [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            (Test-AccountToken $cmd "--rhythm-tag")
        if ($newRunner -or $legacyRunner -or $pythonChild) {
            $result += $proc
        }
    }
    return @($result)
}

function Stop-LegacyAutopilot {
    foreach ($proc in @(Get-AutopilotRunnerProcesses)) {
        Write-Log "AUTOPILOT_STOP fast-path=1 pid=$($proc.ProcessId)"
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

$script:lastAutopilotStart = [datetime]::MinValue
function Ensure-Autopilot {
    param([bool]$BrowserReady)

    if (-not $BrowserReady) { return }
    if (@(Get-AutopilotRunnerProcesses).Count -gt 0) { return }
    if (((Get-Date) - $script:lastAutopilotStart).TotalSeconds -lt 30) { return }

    $runner = Join-Path $repo "scripts\account\run-autopilot-win.ps1"
    Write-Log "AUTOPILOT_START rollback-mode account=$Account"
    Start-Process -FilePath "powershell" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$runner`"", "-Account", $Account
    ) -WindowStyle Hidden -WorkingDirectory $repo | Out-Null
    $script:lastAutopilotStart = Get-Date
}

$browserFailures = 0
Write-Log "SUPERVISOR_START account=$Account profile=$profile port=$port interval=${watchInterval}s"
while ($true) {
    try {
        $browserReady = Ensure-Browser ([ref]$browserFailures)
        Ensure-Worker $browserReady

        $fastPath = $true
        if ($env:PROFI_FAST_PATH -and $env:PROFI_FAST_PATH.Trim() -eq "0") {
            $fastPath = $false
        }
        if ($fastPath) {
            Stop-LegacyAutopilot
        } else {
            Ensure-Autopilot $browserReady
        }
    } catch {
        Write-Log "SUPERVISOR_ERROR $($_.Exception.Message)"
    }
    Start-Sleep -Seconds $watchInterval
}
