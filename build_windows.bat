@echo off
rem Build dist\HekaBrowser.exe on Windows (single file, double-click to run).
rem
rem Prerequisite (once): Python 3.12 from https://www.python.org/downloads/
rem ("Add python.exe to PATH" during install). The py launcher is used here.

cd /d %~dp0

if not exist build-venv (
    py -3.12 -m venv build-venv || goto :nopython
)
call build-venv\Scripts\activate.bat

python -m pip install --upgrade pip
python -m pip install pyqt5 pyqtgraph numpy pyinstaller

python -m PyInstaller heka_browser.spec --noconfirm --clean

rem zip for distribution
powershell -NoProfile -Command "Compress-Archive -Path 'dist\HekaBrowser\*' -DestinationPath 'dist\HekaBrowser-windows.zip' -Force"

echo.
echo Done: dist\HekaBrowser\HekaBrowser.exe  (+ dist\HekaBrowser-windows.zip)
echo Unzip anywhere and double-click HekaBrowser.exe.
echo First launch: SmartScreen may warn -- "More info" ^> "Run anyway".
pause
exit /b 0

:nopython
echo.
echo ERROR: Python 3.12 not found. Install it from https://www.python.org/downloads/
echo        and tick "Add python.exe to PATH", then run this script again.
pause
exit /b 1
