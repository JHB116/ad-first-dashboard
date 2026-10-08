@echo off
rem Ad dashboard: build backup from data\raw (xlsb/csv/xlsx) -> backup\*.json.gz
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PY=python
where python >nul 2>nul || set PY=py
%PY% -c "import pandas, pyxlsb, openpyxl" >nul 2>nul || %PY% -m pip install -r requirements.txt
if not exist data\raw mkdir data\raw
%PY% build_data.py
if errorlevel 1 (
  echo.
  echo [ERROR] backup build failed. See the message above.
  pause
  exit /b 1
)
echo.
echo Done. Drag the newest file in the "backup" folder onto the dashboard.
start "" explorer "%~dp0backup"
pause
