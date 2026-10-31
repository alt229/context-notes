@echo off
rem Puts two shortcuts on your desktop: "Context Notes" starts the app (context-notes.bat: it sets the app up first
rem when it needs to), and "Update Context Notes" downloads the latest version and starts it (update.bat).
rem Double-click this file once. Run it again if you move the folder; it replaces shortcuts of those names.
rem With --no-pause (dookie-update.bat) it doesn't wait for a key at the end. Created 2026-10-30.
setlocal
set "CN_HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $here = $env:CN_HERE.TrimEnd('\'); $desk = [Environment]::GetFolderPath('Desktop'); $sh = New-Object -ComObject WScript.Shell; foreach ($pair in @(@('Context Notes', 'context-notes.bat', 'Start Context Notes'), @('Update Context Notes', 'update.bat', 'Download the latest Context Notes and start it'))) { $link = Join-Path $desk ($pair[0] + '.lnk'); $s = $sh.CreateShortcut($link); $s.TargetPath = Join-Path $here $pair[1]; $s.WorkingDirectory = $here; $s.Description = $pair[2]; $s.Save(); Write-Host ('Made ' + $link) }"
if errorlevel 1 goto :failed
echo.
echo Done. Double-click "Context Notes" on your desktop to start the app, and "Update Context Notes" to get the
echo latest version.
if not "%~1"=="--no-pause" pause
exit /b 0

:failed
echo.
echo Couldn't make the shortcuts. The lines above say why.
pause
exit /b 1
