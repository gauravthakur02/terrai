@echo off
REM TerraAI — Windows build script
REM Produces: dist\terraai.exe  (single binary, no Python install needed)
REM
REM Usage:
REM   build.bat           -- build
REM   build.bat --clean   -- clean dist\ and build\ first

echo 🌍 TerraAI - Windows Build Script
echo.

SET SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM ── Clean ────────────────────────────────────────────────────────────
IF "%1"=="--clean" (
    echo Cleaning dist\ and build\ ...
    IF EXIST dist rmdir /S /Q dist
    IF EXIST build rmdir /S /Q build
    echo.
)

REM ── Virtual env ──────────────────────────────────────────────────────
IF NOT EXIST ".venv" (
    echo Creating virtual environment ...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

REM ── Dependencies ─────────────────────────────────────────────────────
echo Installing dependencies ...
pip install -q --upgrade pip
pip install -q -r requirements.txt
pip install -q pyinstaller

REM ── Build ─────────────────────────────────────────────────────────────
echo.
echo Building executable ...
pyinstaller terraai.spec --noconfirm --log-level WARN

REM ── Result ────────────────────────────────────────────────────────────
IF NOT EXIST "dist\terraai.exe" (
    echo ERROR: Build failed - dist\terraai.exe not found
    exit /b 1
)

echo.
echo Build complete!
echo    Binary: dist\terraai.exe
echo.
echo Test it:
echo    dist\terraai.exe --help
echo    dist\terraai.exe models
