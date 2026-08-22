param(
    [ValidateSet("Start", "Stop", "Restart", "Status")]
    [string]$Action = "Start",

    [ValidateSet("NIFTY 50", "BANK NIFTY")]
    [string]$Underlying = "NIFTY 50",

    [ValidateRange(60, 3600)]
    [int]$CollectorIntervalSeconds = 60
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$runtimeDirectory = Join-Path $projectRoot "artifacts"
$pidFile = Join-Path $runtimeDirectory "red_bar_platform_processes.json"

function Read-PlatformProcesses {
    if (-not (Test-Path $pidFile)) {
        return @()
    }

    try {
        $payload = Get-Content $pidFile -Raw | ConvertFrom-Json
        return @($payload)
    }
    catch {
        Write-Host "Unable to read platform PID file: $pidFile" -ForegroundColor Yellow
        return @()
    }
}

function Get-RunningPlatformProcesses {
    $running = @()
    foreach ($entry in (Read-PlatformProcesses)) {
        $process = Get-Process -Id ([int]$entry.ProcessId) -ErrorAction SilentlyContinue
        if ($null -ne $process) {
            $running += [PSCustomObject]@{
                Name      = [string]$entry.Name
                ProcessId = [int]$entry.ProcessId
                Process   = $process
            }
        }
    }
    return $running
}

function Show-PlatformStatus {
    $running = @(Get-RunningPlatformProcesses)
    if ($running.Count -eq 0) {
        Write-Host "Red Bar platform is not running." -ForegroundColor Yellow
        return
    }

    Write-Host "Red Bar platform processes:" -ForegroundColor Cyan
    foreach ($entry in $running) {
        Write-Host ("  {0,-24} PID {1}" -f $entry.Name, $entry.ProcessId) -ForegroundColor Green
    }
}

function Stop-RedBarPlatform {
    $running = @(Get-RunningPlatformProcesses)
    if ($running.Count -eq 0) {
        Write-Host "No tracked Red Bar platform processes are running." -ForegroundColor Yellow
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        return
    }

    foreach ($entry in ($running | Sort-Object { if ($_.Name -eq "Red Bar Lab UI") { 0 } else { 1 } })) {
        try {
            Stop-Process -Id $entry.ProcessId -Force -ErrorAction Stop
            Write-Host ("Stopped {0} (PID {1})." -f $entry.Name, $entry.ProcessId) -ForegroundColor Green
        }
        catch {
            Write-Host ("Unable to stop {0} (PID {1}): {2}" -f $entry.Name, $entry.ProcessId, $_.Exception.Message) -ForegroundColor Yellow
        }
    }

    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host "Red Bar platform stop command completed." -ForegroundColor Green
}

function Start-TrackedPowerShellProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Command
    )

    $process = Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-Command",
        $Command
    ) -PassThru

    return [PSCustomObject]@{
        Name      = $Name
        ProcessId = $process.Id
        StartedAt = (Get-Date).ToString("o")
    }
}

if ($Action -eq "Status") {
    Show-PlatformStatus
    exit 0
}

if ($Action -eq "Stop") {
    Stop-RedBarPlatform
    exit 0
}

if ($Action -eq "Restart") {
    Stop-RedBarPlatform
}

$alreadyRunning = @(Get-RunningPlatformProcesses)
if ($alreadyRunning.Count -gt 0) {
    Write-Host "Red Bar platform is already running. Use -Action Status or -Action Stop." -ForegroundColor Yellow
    Show-PlatformStatus
    exit 1
}

if (-not $env:UPSTOX_ACCESS_TOKEN) {
    Write-Host "UPSTOX_ACCESS_TOKEN is not set." -ForegroundColor Yellow
    Write-Host '$env:UPSTOX_ACCESS_TOKEN="your-token"' -ForegroundColor Yellow
    exit 1
}

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
$escapedRoot = $projectRoot.Replace("'", "''")
$escapedToken = $env:UPSTOX_ACCESS_TOKEN.Replace("'", "''")
$escapedUnderlying = $Underlying.Replace("'", "''")
$processes = @()

try {
    $collectorCommand = @"
Set-Location '$escapedRoot'
`$env:UPSTOX_ACCESS_TOKEN='$escapedToken'
.\run_market_collector.ps1 -Underlying '$escapedUnderlying' -IntervalSeconds $CollectorIntervalSeconds -Mode auto
"@
    $processes += Start-TrackedPowerShellProcess -Name "Dual Market Collector" -Command $collectorCommand
    Write-Host "Dual Market Collector started." -ForegroundColor Green

    $paperCommand = @"
Set-Location '$escapedRoot'
`$env:UPSTOX_ACCESS_TOKEN='$escapedToken'
.\run_paper_monitor.ps1 -IntervalSeconds 5 -Underlying '$escapedUnderlying'
"@
    $processes += Start-TrackedPowerShellProcess -Name "Upstox Paper Monitor" -Command $paperCommand
    Write-Host "Upstox paper monitor started." -ForegroundColor Green

    $positionMonitorCommand = @"
Set-Location '$escapedRoot'
`$env:UPSTOX_ACCESS_TOKEN='$escapedToken'
.\run_position_monitor.ps1 -IntervalSeconds 5 -Underlying '$escapedUnderlying'
"@
    $processes += Start-TrackedPowerShellProcess -Name "Paper Position Monitor" -Command $positionMonitorCommand
    Write-Host "Fast paper-position monitor started." -ForegroundColor Green

    $uiCommand = @"
Set-Location '$escapedRoot'
`$env:UPSTOX_ACCESS_TOKEN='$escapedToken'
.\run_red_bar.ps1
"@
    $processes += Start-TrackedPowerShellProcess -Name "Red Bar Lab UI" -Command $uiCommand
    Write-Host "Red Bar Lab UI started." -ForegroundColor Green

    $processes | ConvertTo-Json | Set-Content -Path $pidFile -Encoding UTF8
    Write-Host "Red Bar platform started successfully." -ForegroundColor Green
    Write-Host "Stop it with: .\start_red_bar_platform.ps1 -Action Stop" -ForegroundColor Cyan
}
catch {
    Write-Host "Platform startup failed: $($_.Exception.Message)" -ForegroundColor Red
    foreach ($entry in $processes) {
        Stop-Process -Id $entry.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    exit 1
}
