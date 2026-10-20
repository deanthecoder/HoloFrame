@echo off
call "%~dp0run_godot.cmd" --cornell %*
exit /b %errorlevel%
