$ErrorActionPreference = "Continue"
Set-Location -LiteralPath $PSScriptRoot

$root = (Get-Location).Path
$taskName = "AdaptiveAgentChatV5Local"
$pidFile = Join-Path (Join-Path $root "runs") "server.pid"

$taskFound = $false
try {
    $taskFound = [bool](Get-ScheduledTask -TaskName $taskName -ErrorAction Stop)
} catch {}

if ($taskFound) {
    try { Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop } catch {
        # schtasks is a useful fallback when the ScheduledTasks PowerShell
        # module is unavailable or denies a non-admin session.
        & schtasks.exe /End /TN $taskName *> $null
    }
    Write-Host "Adaptive Agent Lab scheduled server stopped." -ForegroundColor Yellow
} else {
    Write-Host "No registered Adaptive Agent Lab server task was found." -ForegroundColor DarkGray
}

if (Test-Path -LiteralPath $pidFile) {
    $rawPid = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    $serverPid = 0
    if ([int]::TryParse($rawPid, [ref]$serverPid) -and $serverPid -gt 0) {
        try {
            $process = Get-Process -Id $serverPid -ErrorAction Stop
            $expectedVenvPython = [IO.Path]::GetFullPath((Join-Path $root ".venv\Scripts\python.exe"))
            $expectedBundledPython = if ($env:USERPROFILE) {
                [IO.Path]::GetFullPath((Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"))
            }
            $actualPath = if ($process.Path) { [IO.Path]::GetFullPath($process.Path) } else { "" }
            if ($actualPath -and ($actualPath -eq $expectedVenvPython -or $actualPath -eq $expectedBundledPython)) {
                Stop-Process -Id $serverPid -ErrorAction SilentlyContinue
                Wait-Process -Id $serverPid -Timeout 5 -ErrorAction SilentlyContinue
                if (Get-Process -Id $serverPid -ErrorAction SilentlyContinue) {
                    Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue
                }
                Write-Host "Adaptive Agent Lab uvicorn process stopped (PID $serverPid)." -ForegroundColor Yellow
            } else {
                Write-Warning "PID file did not point to this project's Python process; it was left untouched."
            }
        } catch {
            Write-Host "The recorded server process is already stopped." -ForegroundColor DarkGray
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
