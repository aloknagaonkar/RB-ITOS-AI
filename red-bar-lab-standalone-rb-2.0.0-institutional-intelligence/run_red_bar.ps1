$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$env:RED_BAR_PORT = if ($env:RED_BAR_PORT) { $env:RED_BAR_PORT } else { "8502" }
$env:PYTHONPATH = $ProjectRoot

python -m streamlit run "$ProjectRoot\red_bar_lab\app.py" `
    --server.port $env:RED_BAR_PORT `
    --server.headless true
