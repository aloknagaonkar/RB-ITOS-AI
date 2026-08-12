@echo off
setlocal
cd /d "%~dp0"
if "%RED_BAR_PORT%"=="" set RED_BAR_PORT=8502
set PYTHONPATH=%CD%
python -m streamlit run "%CD%\red_bar_lab\app.py" --server.port %RED_BAR_PORT%
endlocal
