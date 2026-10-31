@echo off
rem dookie-update.bat - one double-click to bring Dookie's copy of Context Notes up to date (Erin's Windows beta
rem tester): downloads the latest version (git pull), puts the "Context Notes" and "Update Context Notes" shortcuts
rem on the desktop, sets the app up with Python 3.14 if it needs it, and starts it.
rem TEMPORARY, added 2026-10-30. Once his desktop shortcuts work, "Update Context Notes" (update.bat) does this job.
rem Claude reminds Erin about removing it (CLAUDE.md, "Reminders"). To remove: delete this file and its line there.
rem Put it in the context-notes folder (the one with app.py) and double-click it. It runs from a copy in your
rem temporary folder, because the update may replace this file.
setlocal
if "%~1"=="--from-copy" goto :update
copy /y "%~f0" "%TEMP%\dookie-update.bat" >nul
"%TEMP%\dookie-update.bat" --from-copy "%~dp0"
exit /b

:update
cd /d "%~2"
if exist "app.py" goto :found
for %%d in ("%USERPROFILE%\context-notes" "%USERPROFILE%\Documents\context-notes" "%USERPROFILE%\Desktop\context-notes" "%USERPROFILE%\Downloads\context-notes") do if exist "%%~d\app.py" cd /d "%%~d"
if exist "app.py" goto :found
echo Couldn't find Context Notes. Move this file into your context-notes folder (the one with app.py in it)
echo and double-click it again.
goto :fail

:found
echo Updating Context Notes in %CD%
echo.
where git >nul 2>&1
if errorlevel 1 echo Git isn't installed, so it can't update. Install it with: winget install Git.Git
if errorlevel 1 goto :fail
rem A copy of this file that came by message, not by git, would stop git pull from adding the project's own copy.
if not exist "dookie-update.bat" goto :pull
git ls-files --error-unmatch dookie-update.bat >nul 2>&1
if errorlevel 1 del "dookie-update.bat"

:pull
git pull --ff-only
if errorlevel 1 goto :pull_failed
echo.
call make-shortcut.bat --no-pause
echo.
echo Starting Context Notes. The first time, it gets itself ready, which takes a few minutes:
echo leave this window open, and if it asks to install Python 3.14, press Y.
echo.
call context-notes.bat
exit /b 0

:pull_failed
echo.
echo The update didn't download. The lines above say why. Send Erin a photo of this window.

:fail
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
