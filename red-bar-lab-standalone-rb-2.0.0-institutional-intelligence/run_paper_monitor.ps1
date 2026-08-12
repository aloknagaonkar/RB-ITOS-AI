param(
    [ValidateRange(2, 3600)]
    [int]$IntervalSeconds = 5,

    [ValidateRange(10000, 10000000)]
    [double]$Capital = 100000,

    [ValidateSet("NIFTY 50", "BANK NIFTY")]
    [string]$Underlying = "NIFTY 50",

    [ValidateRange(1, 20)]
    [int]$Lots = 1,

    [ValidateRange(0, 100)]
    [double]$MinimumScore = 65
)

if (-not $env:UPSTOX_ACCESS_TOKEN) {
    Write-Host "UPSTOX_ACCESS_TOKEN is not set." -ForegroundColor Yellow
    exit 1
}

python -m red_bar_lab.execution.paper_monitor `
    --interval-seconds $IntervalSeconds `
    --capital $Capital `
    --underlying $Underlying `
    --lots $Lots `
    --minimum-score $MinimumScore
