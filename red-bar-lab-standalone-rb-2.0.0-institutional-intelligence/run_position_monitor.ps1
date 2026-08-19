param(
    [ValidateSet("NIFTY 50", "BANK NIFTY")]
    [string]$Underlying = "NIFTY 50",

    [ValidateRange(2, 60)]
    [int]$IntervalSeconds = 5
)

python -m red_bar_lab.execution.position_monitor `
    --underlying $Underlying `
    --interval-seconds $IntervalSeconds
