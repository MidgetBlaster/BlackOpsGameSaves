@echo off
cd /d "%~dp0"
if exist "%~dp0BlackOpsGameSaves.exe" (
    start "" "%~dp0BlackOpsGameSaves.exe"
    exit /b
)
where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "%~dp0checkpoint_gui.py"
) else (
    python.exe "%~dp0checkpoint_gui.py"
)
