param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('start', 'stop', 'status', 'restart')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtimeDir = Join-Path $projectRoot 'data\runtime'
$logDir = Join-Path $projectRoot 'data\logs'
$healthUrl = 'http://127.0.0.1:8123/api/health'

function Get-ServiceState([string]$serviceName) {
    $pidFile = Join-Path $runtimeDir "$serviceName.json"
    if (-not (Test-Path -LiteralPath $pidFile)) {
        return [pscustomobject]@{ Name=$serviceName; Running=$false; Pid=$null; Reason='no pid file' }
    }
    try {
        $metadata = Get-Content -Raw -LiteralPath $pidFile | ConvertFrom-Json
        if ([System.IO.Path]::GetFullPath([string]$metadata.project_root) -ne $projectRoot) {
            return [pscustomobject]@{ Name=$serviceName; Running=$false; Pid=$metadata.pid; Reason='project mismatch' }
        }
        $process = Get-Process -Id ([int]$metadata.pid) -ErrorAction SilentlyContinue
        if (-not $process) {
            return [pscustomobject]@{ Name=$serviceName; Running=$false; Pid=$metadata.pid; Reason='process exited' }
        }
        $started = [datetime]::Parse([string]$metadata.started_at).ToUniversalTime()
        if ([math]::Abs(($process.StartTime.ToUniversalTime() - $started).TotalSeconds) -gt 5) {
            return [pscustomobject]@{ Name=$serviceName; Running=$false; Pid=$metadata.pid; Reason='pid reused' }
        }
        return [pscustomobject]@{ Name=$serviceName; Running=$true; Pid=$process.Id; Reason='running' }
    } catch {
        return [pscustomobject]@{ Name=$serviceName; Running=$false; Pid=$null; Reason='invalid pid file' }
    }
}

function Start-Platform {
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Python environment missing: $pythonExe" }
    [System.IO.Directory]::CreateDirectory($runtimeDir) | Out-Null
    [System.IO.Directory]::CreateDirectory($logDir) | Out-Null
    foreach ($serviceName in @('api','worker')) {
        $state = Get-ServiceState $serviceName
        if ($state.Running) {
            Write-Output ("{0}: already running (PID {1})" -f $serviceName,$state.Pid)
            continue
        }
        Start-Process -FilePath $pythonExe -ArgumentList '-m','market_lab.runtime',$serviceName `
            -WorkingDirectory $projectRoot -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logDir "$serviceName.log") `
            -RedirectStandardError (Join-Path $logDir "$serviceName-error.log") | Out-Null
        $deadline = [datetime]::UtcNow.AddSeconds(10)
        do { Start-Sleep -Milliseconds 200; $state = Get-ServiceState $serviceName }
        until ($state.Running -or [datetime]::UtcNow -ge $deadline)
        if (-not $state.Running) { throw "$serviceName failed to start. Check data/logs/$serviceName-error.log" }
        if ($serviceName -eq 'worker') {
            Start-Sleep -Milliseconds 750
            $state = Get-ServiceState $serviceName
            if (-not $state.Running) { throw "worker exited during startup. Check data/logs/worker-error.log" }
        }
        Write-Output ("{0}: started (PID {1})" -f $serviceName,$state.Pid)
    }
    $healthDeadline = [datetime]::UtcNow.AddSeconds(10)
    do {
        try { $null = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1; $apiReady = $true }
        catch { $apiReady = $false; Start-Sleep -Milliseconds 250 }
    } until ($apiReady -or [datetime]::UtcNow -ge $healthDeadline)
    if (-not $apiReady) { throw 'API process started but health check failed. Check data/logs/api-error.log' }
}

function Stop-Platform {
    foreach ($serviceName in @('worker','api')) {
        $state = Get-ServiceState $serviceName
        $pidFile = Join-Path $runtimeDir "$serviceName.json"
        if ($state.Running) {
            Stop-Process -Id $state.Pid
            try { Wait-Process -Id $state.Pid -Timeout 10 -ErrorAction SilentlyContinue } catch {}
            Write-Output ("{0}: stopped (PID {1})" -f $serviceName,$state.Pid)
        } else { Write-Output ("{0}: not running ({1})" -f $serviceName,$state.Reason) }
        if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile -Force }
    }
}

function Show-Status {
    foreach ($serviceName in @('api','worker')) {
        $state = Get-ServiceState $serviceName
        if ($state.Running) { Write-Output ("{0}: RUNNING (PID {1})" -f $serviceName,$state.Pid) }
        else { Write-Output ("{0}: STOPPED ({1})" -f $serviceName,$state.Reason) }
    }
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
        Write-Output ("dashboard: AVAILABLE at http://127.0.0.1:8123 (execution: {0})" -f $health.execution)
    } catch { Write-Output 'dashboard: UNAVAILABLE at http://127.0.0.1:8123' }
}

switch ($Action) {
    'start' { Start-Platform; Show-Status }
    'stop' { Stop-Platform; Show-Status }
    'status' { Show-Status }
    'restart' { Stop-Platform; Start-Platform; Show-Status }
}
