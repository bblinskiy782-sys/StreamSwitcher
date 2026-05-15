@echo off
echo ============================================
echo   StreamSwitcher Pro - Full Build
echo ============================================
echo.

:: Step 1: Clean venv
echo [1/4] Creating clean virtual environment...
if exist build_venv rmdir /s /q build_venv
python -m venv build_venv
call build_venv\Scripts\activate.bat

:: Step 2: Install deps
echo [2/4] Installing dependencies...
pip install --quiet PySide6 sounddevice soundfile numpy requests flask lameenc imageio-ffmpeg scipy pydub mutagen schedule pyinstaller

:: Step 3: PyInstaller
echo [3/4] Building EXE with PyInstaller...
pyinstaller build_exe.spec --noconfirm --clean

call deactivate

if not exist "dist\StreamSwitcher\StreamSwitcher.exe" (
    echo.
    echo ERROR: PyInstaller build failed!
    pause
    exit /b 1
)

echo.
echo   EXE build OK: dist\StreamSwitcher\StreamSwitcher.exe
echo.

:: Step 4: Inno Setup (optional)
echo [4/4] Building installer...
set INNO="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist %INNO% (
    %INNO% installer.iss
    if exist "Output\StreamSwitcher_Setup.exe" (
        echo.
        echo ============================================
        echo   BUILD COMPLETE!
        echo ============================================
        echo.
        echo   Portable:   dist\StreamSwitcher\StreamSwitcher.exe
        echo   Installer:  Output\StreamSwitcher_Setup.exe
        echo.
    ) else (
        echo   Inno Setup build failed, but portable EXE is ready.
    )
) else (
    echo.
    echo   Inno Setup not found - skipping installer.
    echo   Install from: https://jrsoftware.org/isdl.php
    echo   Then re-run this script to get StreamSwitcher_Setup.exe
    echo.
    echo ============================================
    echo   BUILD COMPLETE (portable only)
    echo ============================================
    echo.
    echo   Result: dist\StreamSwitcher\StreamSwitcher.exe
    echo   Copy the entire dist\StreamSwitcher folder to any PC.
    echo.
)

pause
