@echo off
rem Starts Context Notes on Windows. Double-click this file, or make a shortcut to it.
rem Uses .venv in this folder (see the README), else the venv in your home folder.
cd /d "%~dp0"
if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else if exist "%USERPROFILE%\venv\Scripts\activate.bat" (
    call "%USERPROFILE%\venv\Scripts\activate.bat"
) else (
    echo No virtual environment found. Follow the Windows steps in README.md first.
    pause
    exit /b 1
)
rem Keep python.exe here, not pythonw.exe: the app needs a console.
python app.py
echo.
echo The app has stopped. Press any key to close this window.
pause >nul
