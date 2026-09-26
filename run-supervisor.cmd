@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Run setup.cmd first.
  exit /b 1
)
".venv\Scripts\python.exe" supervisor.py %*
