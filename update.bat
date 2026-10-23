@echo off
rem Ad dashboard updater - double-click to get the latest program files from GitHub (main)
rem  - Updates only program files. The raw / backup / data folders are not touched.
setlocal
chcp 65001 >nul
set "HERE=%~dp0"
set "SRC=https://raw.githubusercontent.com/jhb116/ad-first-dashboard/main"
set "TMP_DIR=%TEMP%\ad-dashboard-update"
set FILES=build_data.py make_backup.bat requirements.txt calc.js dashboard.html index.html app.py
if exist "%TMP_DIR%" rmdir /s /q "%TMP_DIR%"
mkdir "%TMP_DIR%"

echo Downloading the latest files...
set FAIL=0
for %%F in (%FILES%) do call :get %%F
if not "%FAIL%"=="0" (
  echo.
  echo [ERROR] Download failed. Nothing was changed. Check the internet connection and try again.
  rmdir /s /q "%TMP_DIR%"
  pause
  exit /b 1
)

rem Every file downloaded - now replace them
for %%F in (%FILES%) do copy /y "%TMP_DIR%\%%F" "%HERE%%%F" >nul
rmdir /s /q "%TMP_DIR%"
echo.
echo Updated: %FILES%
findstr /c:"BUILD_VERSION = " "%HERE%build_data.py"
echo.
echo Done. Run make_backup.bat to build a new backup.
pause
exit /b 0

:get
curl -fsSL "%SRC%/%~1" -o "%TMP_DIR%\%~1" 2>nul
if errorlevel 1 powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing '%SRC%/%~1' -OutFile '%TMP_DIR%\%~1' } catch { exit 1 }"
if errorlevel 1 (echo   [X] %~1 & set FAIL=1 & exit /b 0)
for %%S in ("%TMP_DIR%\%~1") do if %%~zS==0 (echo   [X] %~1 is empty & set FAIL=1 & exit /b 0)
echo   [OK] %~1
exit /b 0
