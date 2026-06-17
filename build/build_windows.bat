@echo off
REM Build the Windows app:  build\build_windows.bat
REM Produces: dist\EXO\EXO.exe
setlocal
cd /d "%~dp0\.."

set PY=python
echo ==^> Using Python: %PY%

echo ==^> Installing build dependencies
%PY% -m pip install -q -r requirements.txt
%PY% -m pip install -q -r requirements-desktop.txt

echo ==^> Generating icon
%PY% build\make_icon.py

echo ==^> Cleaning previous build
if exist "dist\EXO" rmdir /s /q "dist\EXO"

echo ==^> Running PyInstaller
%PY% -m PyInstaller --noconfirm --clean FuturesBot.spec

echo.
echo ==^> Done: dist\EXO\EXO.exe
echo    Double-click EXO.exe to launch. (SmartScreen on first run:
echo    "More info" -^> "Run anyway" for an unsigned build.)
echo    To distribute one file, zip the "EXO" folder.
endlocal
