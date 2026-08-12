param(
    [ValidateSet("NIFTY 50", "BANK NIFTY")]
    [string]$Underlying = "NIFTY 50",

    [ValidateRange(60, 3600)]
    [int]$IntervalSeconds = 60,

    [ValidateSet("auto", "online", "offline")]
    [string]$Mode = "auto"
)

if (-not $env:UPSTOX_ACCESS_TOKEN) {
    Write-Host "UPSTOX_ACCESS_TOKEN is not set in this PowerShell session." -ForegroundColor Yellow
    Write-Host 'Set it first: $env:UPSTOX_ACCESS_TOKEN="your-token"' -ForegroundColor Yellow
    exit 1
}

python -m red_bar_lab.collector.runner `
    --underlying $Underlying `
    --interval-seconds $IntervalSeconds `
    --mode $Mode
