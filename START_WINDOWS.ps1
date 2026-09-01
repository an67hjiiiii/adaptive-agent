param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$root = (Get-Location).Path
$taskName = "AdaptiveAgentChatV5Local"
$appUrl = "http://127.0.0.1:8000"
$expectedVersion = "0.6.3"
$runsDir = Join-Path $root "runs"
$pidFile = Join-Path $runsDir "server.pid"
$runner = Join-Path $root "scripts\server_host.ps1"
New-Item -ItemType Directory -Force -Path $runsDir | Out-Null

function Test-AppHealth {
    try {
        $health = Invoke-RestMethod -Uri "$appUrl/api/health" -TimeoutSec 3
        if ($health.status -ne "ok" -or $health.service -ne "adaptive-agent-lab" -or $health.version -ne $expectedVersion) { return $false }
        # A health endpoint alone can belong to another process on port 8000. Check
        # the app contract too, without printing config or credentials.
        $config = Invoke-RestMethod -Uri "$appUrl/api/config" -TimeoutSec 3
        return [bool]($config.chat_strategy -eq "adaptive-auto" -and $config.model_options -and $config.app_version -eq $expectedVersion)
    } catch {
        return $false
    }
}

function Test-PythonRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string[]]$Arguments = @()
    )
    try {
        & $Path @Arguments -c "import sys" 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Resolve-BootstrapPython {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand -and (Test-PythonRuntime -Path $pythonCommand.Source)) {
        return @($pythonCommand.Source, @())
    }

    $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyCommand -and (Test-PythonRuntime -Path $pyCommand.Source -Arguments @("-3"))) {
        return @($pyCommand.Source, @("-3"))
    }

    $profileRoot = $env:USERPROFILE
    if ($profileRoot) {
        $bundled = Join-Path $profileRoot ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
        if (Test-Path -LiteralPath $bundled) { return @($bundled, @()) }
    }
    throw "Python 3.12+ was not found. Install Python or create .venv before starting the app."
}

Write-Host ""
Write-Host "Adaptive Agent Lab v0.6.3 - REAL LOCAL APP" -ForegroundColor Cyan

# First run: create a local .env template only when it does not exist.
# This never overwrites an existing key/configuration.
if (!(Test-Path -LiteralPath ".env") -and (Test-Path -LiteralPath ".env.example")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created .env from .env.example. Fake provider works immediately; add a provider key later if needed." -ForegroundColor DarkGray
}

if (Test-AppHealth) {
    Write-Host "Server is already online at $appUrl" -ForegroundColor Green
    if (!$NoBrowser) { Start-Process $appUrl }
    exit 0
}

if (!(Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    $bootstrap = Resolve-BootstrapPython
    & $bootstrap[0] $bootstrap[1] -m venv .venv
}

$pythonPath = (Resolve-Path ".venv\Scripts\python.exe").Path
& $pythonPath -c "import fastapi,uvicorn,pydantic,dotenv,openai,httpx" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing project dependencies..." -ForegroundColor Yellow
    $pipOutput = (& $pythonPath -m pip install --disable-pip-version-check -r requirements.txt 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        if ($pipOutput -match "(?i)(network|name resolution|temporary failure|connection (?:aborted|reset|refused)|proxy|timed out|could not fetch|no matching distribution|ssl)") {
            Write-Host "NETWORK_DEPENDENCY_BLOCKED: could not download project dependencies." -ForegroundColor Yellow
            Write-Host "Run '.\.venv\Scripts\python.exe -m pip install -r requirements.txt' on a network-enabled machine, then rerun START_WINDOWS.ps1." -ForegroundColor Yellow
            exit 2
        }
        Write-Host "DEPENDENCY_INSTALL_FAILED: project dependencies could not be installed." -ForegroundColor Red
        Write-Host "Inspect pip output above and rerun START_WINDOWS.ps1 after fixing the dependency issue." -ForegroundColor Red
        exit 1
    }
}

$taskRegistered = $false
try {
    if (!(Test-Path -LiteralPath $runner)) { throw "Missing server runner: $runner" }
    $powershellPath = (Get-Command powershell.exe).Source
    $runnerArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -PythonPath `"$pythonPath`" -Root `"$root`""
    $action = New-ScheduledTaskAction -Execute $powershellPath -Argument $runnerArgs -WorkingDirectory $root
    $principal = New-ScheduledTaskPrincipal `
        -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) `
        -LogonType Interactive `
        -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName
    $taskRegistered = $true
} catch {
    Write-Warning "Scheduled Task unavailable; starting a detached local process instead."
    try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}
}

if (!$taskRegistered) {
    $stdoutLog = Join-Path $runsDir "server.stdout.log"
    $stderrLog = Join-Path $runsDir "server.stderr.log"
    $process = Start-Process -FilePath $pythonPath `
        -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log" `
        -WorkingDirectory $root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
    Set-Content -LiteralPath $pidFile -Value ([string]$process.Id) -Encoding ascii
}

$online = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 500
    if (Test-AppHealth) { $online = $true; break }
}
if (!$online) {
    throw "Server did not become healthy. Inspect runs\server.stderr.log (credentials are not logged by the app)."
}

Write-Host "Server online: $appUrl" -ForegroundColor Green
Write-Host "Provider keys remain server-side in .env; startup logs contain no key values." -ForegroundColor DarkGray
if (!$NoBrowser) { Start-Process $appUrl }
