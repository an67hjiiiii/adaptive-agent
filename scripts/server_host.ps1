param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$Root
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $Root
$runsDir = Join-Path $Root "runs"
$pidFile = Join-Path $runsDir "server.pid"
$stdoutLog = Join-Path $runsDir "server.stdout.log"
$stderrLog = Join-Path $runsDir "server.stderr.log"
New-Item -ItemType Directory -Force -Path $runsDir | Out-Null

# Keep the child PID so STOP_WINDOWS.ps1 can stop the actual uvicorn process,
# even when Task Scheduler only stops this host process.
$process = Start-Process -FilePath $PythonPath `
    -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log" `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
Set-Content -LiteralPath $pidFile -Value ([string]$process.Id) -Encoding ascii

try {
    Wait-Process -Id $process.Id
} finally {
    if (Test-Path -LiteralPath $pidFile) {
        try {
            if ((Get-Content -LiteralPath $pidFile -Raw).Trim() -eq [string]$process.Id) {
                Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
            }
        } catch {}
    }
}
