@echo off
REM Build a single-file Windows .exe of btt_postprocess.py.
REM
REM Requirements (one-time setup):
REM   1. Install Python 3.10+ from https://www.python.org/  (tick "Add to PATH")
REM   2. Open a fresh Command Prompt and run:
REM        pip install pyinstaller Pillow
REM
REM Then double-click this .bat file (or run it from a terminal in this folder).
REM Output: dist\btt_postprocess.exe  (~15 MB, no Python install needed to run it)

setlocal
cd /d "%~dp0"

echo === Building btt_postprocess.exe ===
echo.

pyinstaller ^
    --onefile ^
    --console ^
    --name btt_postprocess ^
    --clean ^
    src\btt_postprocess.py

if errorlevel 1 (
    echo.
    echo BUILD FAILED. Make sure you ran:  pip install pyinstaller Pillow
    pause
    exit /b 1
)

echo.
echo === Done ===
echo The exe is at: %CD%\dist\btt_postprocess.exe
echo.
pause
