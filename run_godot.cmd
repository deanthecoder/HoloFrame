@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Python environment not found. Follow the Windows setup in README.md. 1>&2
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0run_godot.py" %*
exit /b %errorlevel%
