param(
    [ValidateSet("NIFTY 50", "BANK NIFTY")]
    [string]$Underlying = "NIFTY 50",

    [ValidateRange(60, 3600)]
    [int]$CollectorIntervalSeconds = 60
)

if (-not $env:UPSTOX_ACCESS_TOKEN) {
    Write-Host "UPSTOX_ACCESS_TOKEN is not set." -ForegroundColor Yellow
    Write-Host '$env:UPSTOX_ACCESS_TOKEN="your-token"' -ForegroundColor Yellow
    exit 1
}

$collectorCommand = @"
Set-Location '$PWD'
`$env:UPSTOX_ACCESS_TOKEN='$env:UPSTOX_ACCESS_TOKEN'
.\run_market_collector.ps1 -Underlying '$Underlying' -IntervalSeconds $CollectorIntervalSeconds -Mode auto
"@

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    $collectorCommand
)

Write-Host "Dual Market Collector started in a separate PowerShell window." -ForegroundColor Green


if ($env:UPSTOX_ACCESS_TOKEN) {
    $paperCommand = @"
Set-Location '$PWD'
`$env:UPSTOX_ACCESS_TOKEN='$env:UPSTOX_ACCESS_TOKEN'
.\run_paper_monitor.ps1 -IntervalSeconds 5 -Underlying '$Underlying'
"@

    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        $paperCommand
    )
    Write-Host "Upstox paper monitor started in a separate PowerShell window." -ForegroundColor Green
}
else {
    Write-Host "UPSTOX_ACCESS_TOKEN not set; paper monitor was not auto-started." -ForegroundColor Yellow
}

$positionMonitorCommand = @"
Set-Location '$PWD'
`$env:UPSTOX_ACCESS_TOKEN='$env:UPSTOX_ACCESS_TOKEN'
.\run_position_monitor.ps1 -IntervalSeconds 5 -Underlying '$Underlying'
"@

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    $positionMonitorCommand
)

Write-Host "Fast paper-position monitor started in a separate PowerShell window." -ForegroundColor Green

Write-Host "Starting Red Bar Lab UI..." -ForegroundColor Green

.\run_red_bar.ps1
