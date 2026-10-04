@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0scripts\install_codex.py" %*
) else (
    python "%~dp0scripts\install_codex.py" %*
)
if errorlevel 1 (
    echo Installation failed. Review the output above.
) else (
    echo Restart Codex once to load the plugin. After reboot, simply open Codex.
)
pause
