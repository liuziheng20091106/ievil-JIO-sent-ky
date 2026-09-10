@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Run: python -m venv .venv
  popd
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py %*
set "game_exit=%errorlevel%"
popd
if not "%game_exit%"=="0" pause
exit /b %game_exit%
