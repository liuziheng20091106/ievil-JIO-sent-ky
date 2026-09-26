@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt -r gateway\requirements.txt
if errorlevel 1 goto failed
pushd frontend
call npm.cmd run build
if errorlevel 1 goto frontend_failed
popd
popd
echo Setup complete. Run start.cmd, then open http://localhost:8000
exit /b 0

:frontend_failed
popd
:failed
popd
echo Setup failed. Check the error above.
exit /b 1
