@echo off
cd /d "%~dp0" || exit /b 1

if not exist ".venv\Scripts\python.exe" (
    echo The evaluator's Python environment is missing. See README.md for setup.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -B -m streamlit run app.py --server.address 127.0.0.1 --server.headless false
if errorlevel 1 pause
