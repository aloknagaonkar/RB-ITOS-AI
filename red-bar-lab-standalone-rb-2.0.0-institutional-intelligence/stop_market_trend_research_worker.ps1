param([int]$TimeoutSeconds = 20)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$artifactsRoot = if ($env:RED_BAR_ARTIFACTS_ROOT) { $env:RED_BAR_ARTIFACTS_ROOT } else { "artifacts/red_bar" }
$workerRoot = Join-Path $projectRoot (Join-Path $artifactsRoot "market_trend_research")
$statusPath = Join-Path $workerRoot "supervisor_state.json"
$stopPath = Join-Path $workerRoot "stop.request"
New-Item -ItemType Directory -Path $workerRoot -Force | Out-Null

$tempPath = "$stopPath.$PID.tmp"
Set-Content -Path $tempPath -Value ((Get-Date).ToUniversalTime().ToString("o")) -Encoding UTF8
Move-Item -Path $tempPath -Destination $stopPath -Force

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
do {
    Start-Sleep -Milliseconds 500
    if (Test-Path $statusPath) {
        try {
            $status = Get-Content $statusPath -Raw | ConvertFrom-Json
            if ($status.supervisor_state -eq "STOPPED") {
                Write-Host "STOPPED" -ForegroundColor Green
                exit 0
            }
        } catch { }
    }
} while ((Get-Date) -lt $deadline)

Write-Host "STOP_REQUESTED: supervisor did not confirm STOPPED within timeout." -ForegroundColor Yellow
Write-Host "No broad Python process termination was attempted."
exit 1
