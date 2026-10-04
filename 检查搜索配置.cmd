@echo off
setlocal
cd /d "%~dp0"
python "%~dp0scripts\check_sources.py"
pause
