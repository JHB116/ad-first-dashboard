@echo off
rem Ad dashboard: build backup from the "raw" folder (xlsb/csv/xlsx) -> "backup" folder
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PY=python
where python >nul 2>nul || set PY=py
if not exist raw mkdir raw
dir /b raw\*.xlsb raw\*.csv raw\*.xlsx >nul 2>nul
if errorlevel 1 (
  echo Put the raw files [xlsb / csv / xlsx] into the "raw" folder that just opened, then run this again.
  start "" explorer "%~dp0raw"
  pause
  exit /b 0
)
%PY% -c "import pandas, pyxlsb, openpyxl" >nul 2>nul || %PY% -m pip install -r requirements.txt
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
