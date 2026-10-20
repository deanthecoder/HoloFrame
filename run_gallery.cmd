@echo off
call "%~dp0run_godot.cmd" --gallery %*
exit /b %errorlevel%
