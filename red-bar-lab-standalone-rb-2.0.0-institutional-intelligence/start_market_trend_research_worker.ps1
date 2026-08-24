param()

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
Set-Location $projectRoot

if (-not $env:UPSTOX_ACCESS_TOKEN) {
    Write-Host "CONFIGURATION_ERROR: UPSTOX_ACCESS_TOKEN_MISSING" -ForegroundColor Red
    Write-Host '$env:UPSTOX_ACCESS_TOKEN="your-token"' -ForegroundColor Yellow
    exit 2
}

if ($env:MARKET_TREND_RESEARCH_CALENDAR_VERIFIED -notin @("1", "true", "TRUE", "yes", "YES", "on", "ON")) {
    Write-Host "CONFIGURATION_ERROR: CALENDAR_UNVERIFIED" -ForegroundColor Red
    Write-Host '$env:MARKET_TREND_RESEARCH_CALENDAR_VERIFIED="true"' -ForegroundColor Yellow
    Write-Host "Declare MARKET_TREND_RESEARCH_HOLIDAYS when verified holidays are applicable." -ForegroundColor Yellow
    exit 2
}

$python = (Get-Command python -ErrorAction Stop).Source
$env:MARKET_TREND_RESEARCH_RUNTIME_ENABLED = "true"
$env:MARKET_TREND_RESEARCH_PROVIDER = "UPSTOX"
$env:MARKET_TREND_RESEARCH_UNATTENDED = "true"

$artifactsSetting = if ($env:RED_BAR_ARTIFACTS_ROOT) { $env:RED_BAR_ARTIFACTS_ROOT } else { "artifacts/red_bar" }
$artifactsRoot = if ([System.IO.Path]::IsPathRooted($artifactsSetting)) {
    $artifactsSetting
} else {
    Join-Path $projectRoot $artifactsSetting
}
$workerRoot = Join-Path $artifactsRoot "market_trend_research"
$statusPath = Join-Path $workerRoot "supervisor_state.json"
New-Item -ItemType Directory -Path $workerRoot -Force | Out-Null

if (Test-Path $statusPath) {
    try {
        $existing = Get-Content $statusPath -Raw | ConvertFrom-Json
        $existingProcess = Get-Process -Id ([int]$existing.supervisor_pid) -ErrorAction SilentlyContinue
        if ($null -ne $existingProcess -and $existing.supervisor_state -in @("STARTING", "RUNNING", "BACKING_OFF", "CIRCUIT_OPEN")) {
            Write-Host "ALREADY_RUNNING" -ForegroundColor Yellow
            Write-Host "Status: $statusPath"
            exit 0
        }
    } catch { }
}

$arguments = @("-m", "red_bar_lab.execution.run_market_trend_research_supervisor")
$launched = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru

$deadline = (Get-Date).AddSeconds(8)
do {
    Start-Sleep -Milliseconds 250
    $launched.Refresh()
    if (Test-Path $statusPath) {
        try {
            $status = Get-Content $statusPath -Raw | ConvertFrom-Json
            if ([int]$status.supervisor_pid -eq $launched.Id -and $status.supervisor_state -eq "RUNNING") {
                Write-Host "STARTED" -ForegroundColor Green
                Write-Host "Status: $statusPath"
                exit 0
            }
            if ([int]$status.supervisor_pid -eq $launched.Id -and $status.supervisor_state -eq "CONFIGURATION_ERROR") {
                Write-Host "CONFIGURATION_ERROR: $($status.safe_reason)" -ForegroundColor Red
                Write-Host "Status: $statusPath"
                exit 2
            }
            if ($launched.HasExited -and $launched.ExitCode -eq 3) {
                Write-Host "ALREADY_RUNNING" -ForegroundColor Yellow
                Write-Host "Status: $statusPath"
                exit 0
            }
        } catch { }
    }
    elseif ($launched.HasExited) {
        Write-Host "CONFIGURATION_ERROR: SUPERVISOR_EXITED_$($launched.ExitCode)" -ForegroundColor Red
        Write-Host "Status: $statusPath"
        exit 2
    }
} while ((Get-Date) -lt $deadline)

Write-Host "STARTING" -ForegroundColor Yellow
Write-Host "Status: $statusPath"
exit 0
