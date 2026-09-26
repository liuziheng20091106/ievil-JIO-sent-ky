@echo off
rem Release wrapper: pack the Windows build into a zip and upload it, the release
rem APK and the standalone Updater.exe (Windows installer) to S3-compatible
rem storage; then refresh data/downloads.json and data/updates.json.
rem See tools\package-release.py.
rem Call it as `package-release.cmd [--dry-run|--skip-zip|--no-downloads|--no-updater|--no-updates]`.
rem This file is deliberately ASCII-only so the console codepage never matters.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -X utf8 "%ROOT%tools\package-release.py" %*
exit /b %ERRORLEVEL%