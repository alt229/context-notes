@echo off
rem Puts a "Context Notes" shortcut on your desktop that starts the app from this folder, the same way
rem context-notes.bat does (this folder's virtual environment, then python app.py). Double-click this file once.
rem Run it again if you move the folder. It replaces a "Context Notes" shortcut that's already on the desktop.
setlocal
set "CN_HERE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $here = $env:CN_HERE.TrimEnd('\'); $link = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Context Notes.lnk'; $s = (New-Object -ComObject WScript.Shell).CreateShortcut($link); $s.TargetPath = Join-Path $here 'context-notes.bat'; $s.WorkingDirectory = $here; $s.Description = 'Start Context Notes'; $s.Save(); Write-Host ('Made ' + $link)"
if errorlevel 1 (
    echo.
    echo Couldn't make the shortcut. The lines above say why.
    pause
    exit /b 1
)
echo.
echo Done. Double-click "Context Notes" on your desktop to start the app.
pause
