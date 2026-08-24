param([int]$TimeoutSeconds = 20)

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
$stopPath = Join-Path $workerRoot "stop.request"
New-Item -ItemType Directory -Path $workerRoot -Force | Out-Null

function Stop-ValidatedProcess {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$RequiredMarker
    )
    if ($ProcessId -le 0) { return $false }
    $candidate = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $candidate -or -not $candidate.CommandLine) { return $false }
    if ($candidate.CommandLine -notlike "*$RequiredMarker*") { return $false }
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    return $true
}

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
                Remove-Item $stopPath -Force -ErrorAction SilentlyContinue
                Write-Host "STOPPED" -ForegroundColor Green
                exit 0
            }
        } catch { }
    }
} while ((Get-Date) -lt $deadline)

Write-Host "Graceful stop timed out; attempting only validated recorded PIDs." -ForegroundColor Yellow
try {
    if (Test-Path $statusPath) {
        $status = Get-Content $statusPath -Raw | ConvertFrom-Json
        if ($status.child_pid) {
            Stop-ValidatedProcess -ProcessId ([int]$status.child_pid) -RequiredMarker "run_market_trend_research_runtime" | Out-Null
        }
        if ($status.supervisor_pid) {
            Stop-ValidatedProcess -ProcessId ([int]$status.supervisor_pid) -RequiredMarker "run_market_trend_research_supervisor" | Out-Null
        }
        Remove-Item $stopPath -Force -ErrorAction SilentlyContinue
        Write-Host "STOPPED_BY_TARGETED_FALLBACK" -ForegroundColor Yellow
        exit 0
    }
}
catch {
    Write-Host "TARGETED_STOP_FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "STOP_REQUESTED: no validated Market Trend Research PID could be stopped." -ForegroundColor Yellow
exit 1
