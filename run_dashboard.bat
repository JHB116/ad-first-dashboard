@echo off
rem Ad dashboard: run the dashboard on this PC (no server memory limit for uploads)
rem Opens http://localhost:8501 in the browser. Close this window to stop.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PY=python
where python >nul 2>nul || set PY=py
%PY% -c "import streamlit, pandas, pyxlsb, openpyxl" >nul 2>nul || %PY% -m pip install -r requirements.txt
%PY% -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false
if errorlevel 1 pause
