@echo off
rem Ad dashboard backup builder
rem  - Drag raw file(s) onto this .bat  : build a backup from just those files
rem  - Double-click                    : build a backup from everything in the "raw" folder
setlocal
set "HERE=%~dp0"
set PYTHONIOENCODING=utf-8
set PY=python
where python >/dev/null 2>/dev/null || set PY=py
%PY% -c "import pandas, pyxlsb, openpyxl" >/dev/null 2>/dev/null || %PY% -m pip install -r "%HERE%requirements.txt"
if not "%~1"=="" (
  %PY% "%HERE%build_data.py" --row %*
  goto done
)
if not exist "%HERE%raw" mkdir "%HERE%raw"
dir /b "%HERE%raw\*.xlsb" "%HERE%raw\*.csv" "%HERE%raw\*.xlsx" >/dev/null 2>nul
if errorlevel 1 (
  echo Put the raw files [xlsb / csv / xlsx] into the "raw" folder that just opened, then run this again.
  echo Or drag a raw file onto this .bat icon.
  start "" explorer "%HERE%raw"
  pause
  exit /b 0
)
cd /d "%HERE%"
%PY% build_data.py
:done
if errorlevel 1 (
  echo.
  echo [ERROR] backup build failed. See the message above.
  pause
  exit /b 1
)
echo.
echo Done. Drag the newest file in the "backup" folder onto the dashboard.
start "" explorer "%HERE%backup"
pause
