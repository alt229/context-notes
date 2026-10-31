@echo off
rem Updates Context Notes on Windows: downloads the latest version (git pull), sets up or tops up this folder's .venv
rem (make_venv.py), then starts the app. Double-click this file, or the "Update Context Notes" shortcut
rem make-shortcut.bat makes. It runs from a copy in your temporary folder, because git pull may replace this file
rem while it runs. Created 2026-10-30.
setlocal
if "%~1"=="--from-copy" goto :update
copy /y "%~f0" "%TEMP%\context-notes-update.bat" >nul
"%TEMP%\context-notes-update.bat" --from-copy "%~dp0"
exit /b

:update
cd /d "%~2"
echo Updating Context Notes in %CD%
echo.
where git >nul 2>&1
if errorlevel 1 echo Git isn't installed, so it can't update. Install it with: winget install Git.Git
if errorlevel 1 goto :fail
git pull --ff-only
if errorlevel 1 goto :pull_failed
echo.
if not exist ".venv\Scripts\python.exe" goto :start
".venv\Scripts\python.exe" make_venv.py --ready >nul 2>&1
if errorlevel 1 goto :start
echo Installing anything the new version needs...
".venv\Scripts\python.exe" make_venv.py --yes
if errorlevel 1 goto :setup_failed

:start
echo.
echo Up to date. Starting Context Notes...
echo.
rem context-notes.bat sets .venv up first when it's missing or on the wrong Python.
call "%~2context-notes.bat"
exit /b 0

:pull_failed
echo.
echo The update didn't download. The lines above say why. If they mention "local changes", a file in this folder
echo was edited here. Send a photo of this window to whoever gave you the app.
goto :fail

:setup_failed
echo.
echo Installing what the new version needs didn't finish. The lines above say why. Send a photo of this window to
echo whoever gave you the app.

:fail
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
