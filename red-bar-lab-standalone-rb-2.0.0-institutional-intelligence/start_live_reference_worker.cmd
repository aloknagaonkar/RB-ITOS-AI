@echo off
setlocal
cd /d "%~dp0"
python -m red_bar_lab.execution.live_reference_worker --underlying "NIFTY 50" --interval-seconds 60
endlocal
