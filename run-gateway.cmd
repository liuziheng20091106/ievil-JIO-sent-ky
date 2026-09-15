@echo off
setlocal
cd /d "%~dp0"
if exist "gateway\.env" for /f "usebackq tokens=1,* delims==" %%A in ("gateway\.env") do if not "%%A"=="" set "%%A=%%B"
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Create it and install gateway\requirements.txt first.
  exit /b 1
)
".venv\Scripts\python.exe" -m gateway.gateway %*
