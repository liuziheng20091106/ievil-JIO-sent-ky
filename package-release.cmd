@echo off
rem Release wrapper: pack the Windows build into a zip and upload it together
rem with the release APK to S3-compatible storage (see tools\package-release.py).
rem Call it as `package-release.cmd [--dry-run|--skip-zip|--no-downloads]`.
rem This file is deliberately ASCII-only so the console codepage never matters.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -X utf8 "%ROOT%tools\package-release.py" %*
exit /b %ERRORLEVEL%