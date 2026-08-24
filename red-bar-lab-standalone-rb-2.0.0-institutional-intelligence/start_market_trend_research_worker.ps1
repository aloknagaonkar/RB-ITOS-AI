param()

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
Set-Location $projectRoot

if (-not $env:UPSTOX_ACCESS_TOKEN) {
    Write-Host "CONFIGURATION_ERROR: UPSTOX_ACCESS_TOKEN_MISSING" -ForegroundColor Red
    Write-Host '$env:UPSTOX_ACCESS_TOKEN="your-token"' -ForegroundColor Yellow
    exit 2
}

$python = (Get-Command python -ErrorAction Stop).Source
$env:MARKET_TREND_RESEARCH_RUNTIME_ENABLED = "true"
$env:MARKET_TREND_RESEARCH_PROVIDER = "UPSTOX"
$env:MARKET_TREND_RESEARCH_UNATTENDED = "true"

$artifactsRoot = if ($env:RED_BAR_ARTIFACTS_ROOT) { $env:RED_BAR_ARTIFACTS_ROOT } else { "artifacts/red_bar" }
$workerRoot = Join-Path $projectRoot (Join-Path $artifactsRoot "market_trend_research")
$statusPath = Join-Path $workerRoot "supervisor_state.json"
New-Item -ItemType Directory -Path $workerRoot -Force | Out-Null

$arguments = @("-m", "red_bar_lab.execution.run_market_trend_research_supervisor")
Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden | Out-Null

$deadline = (Get-Date).AddSeconds(8)
do {
    Start-Sleep -Milliseconds 250
    if (Test-Path $statusPath) {
        try {
            $status = Get-Content $statusPath -Raw | ConvertFrom-Json
            if ($status.supervisor_state -eq "RUNNING") {
                Write-Host "STARTED" -ForegroundColor Green
                Write-Host "Status: $statusPath"
                exit 0
            }
            if ($status.supervisor_state -eq "CONFIGURATION_ERROR") {
                Write-Host "CONFIGURATION_ERROR: $($status.safe_reason)" -ForegroundColor Red
                Write-Host "Status: $statusPath"
                exit 2
            }
        } catch { }
    }
} while ((Get-Date) -lt $deadline)

Write-Host "ALREADY_RUNNING or STARTING" -ForegroundColor Yellow
Write-Host "Status: $statusPath"
exit 0
