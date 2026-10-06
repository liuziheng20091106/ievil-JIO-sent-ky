@echo off
rem Compress oversized songs in resources\audio; originals are backed up.
rem ASCII-only wrapper; all user-facing text comes from Python in UTF-8.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -X utf8 "%ROOT%tools\compress-audio.py" %*
set "RESULT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %RESULT%
