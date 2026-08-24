param()

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$artifactsSetting = if ($env:RED_BAR_ARTIFACTS_ROOT) { $env:RED_BAR_ARTIFACTS_ROOT } else { "artifacts/red_bar" }
$artifactsRoot = if ([System.IO.Path]::IsPathRooted($artifactsSetting)) {
    $artifactsSetting
} else {
    Join-Path $projectRoot $artifactsSetting
}
$workerRoot = Join-Path $artifactsRoot "market_trend_research"
$statusPath = Join-Path $workerRoot "supervisor_state.json"
$maximumAgeSeconds = 30.0
if ($env:MARKET_TREND_RESEARCH_SUPERVISOR_STATUS_MAX_AGE_SECONDS) {
    $parsedAge = 0.0
    if ([double]::TryParse($env:MARKET_TREND_RESEARCH_SUPERVISOR_STATUS_MAX_AGE_SECONDS, [ref]$parsedAge) -and $parsedAge -gt 0) {
        $maximumAgeSeconds = $parsedAge
    }
}

if (-not (Test-Path $statusPath)) {
    Write-Host "STATUS_UNAVAILABLE" -ForegroundColor Yellow
    exit 1
}

try {
    $status = Get-Content $statusPath -Raw | ConvertFrom-Json
    $heartbeat = [DateTimeOffset]::Parse([string]$status.heartbeat_at)
    $heartbeatIst = [System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId($heartbeat, "India Standard Time")
    $age = ([DateTimeOffset]::UtcNow - $heartbeat.ToUniversalTime()).TotalSeconds
    if ($age -lt -1 -or $age -gt $maximumAgeSeconds) {
        Write-Host "STATUS_UNAVAILABLE" -ForegroundColor Yellow
        exit 1
    }
    Write-Host ("Supervisor state : {0}" -f $status.supervisor_state)
    Write-Host ("Supervisor PID   : {0}" -f $status.supervisor_pid)
    Write-Host ("Worker PID       : {0}" -f $status.child_pid)
    Write-Host ("Heartbeat        : {0}" -f $heartbeatIst.ToString("dd MMM yyyy, h:mm:ss tt 'IST'"))
    Write-Host ("Heartbeat age    : {0:N1} seconds" -f $age)
    Write-Host ("Last child exit  : {0}" -f $status.last_child_exit_at)
    Write-Host ("Last exit code   : {0}" -f $status.last_child_exit_code)
    Write-Host ("Restart count    : {0}" -f $status.restart_count)
    Write-Host ("Rapid failures   : {0}" -f $status.consecutive_rapid_failures)
    Write-Host ("Next restart     : {0}" -f $status.next_restart_at)
    Write-Host ("Last safe reason : {0}" -f $status.safe_reason)
    Write-Host ("Authority        : {0}" -f $status.authority)
    exit 0
}
catch {
    Write-Host "STATUS_UNAVAILABLE" -ForegroundColor Yellow
    exit 1
}
