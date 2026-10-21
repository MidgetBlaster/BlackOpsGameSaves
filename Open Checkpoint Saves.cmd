@echo off
if exist "%~dp0..\Game Save\Open Game Save.cmd" (
    start "" "%~dp0..\Game Save\Open Game Save.cmd"
    exit /b
)
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "%~dp0checkpoint_gui.py"
) else (
    python.exe "%~dp0checkpoint_gui.py"
)
