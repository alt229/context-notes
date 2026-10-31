@echo off
rem Starts Context Notes on Windows. Double-click this file, or the "Context Notes" shortcut make-shortcut.bat makes.
rem Every start it checks this folder's .venv (make_venv.py --ready). If it's missing, on another Python or damaged,
rem it sets it up first with the Python version in .python-version (make_venv.py --yes), offering to install that
rem Python with winget when it isn't there. The old .venv is kept as .venv-<version>. Created 2026-10-24, modified
rem 2026-10-30.
setlocal
cd /d "%~dp0"
set "CN_PIN="
for /f "usebackq delims=" %%v in (".python-version") do if not defined CN_PIN set "CN_PIN=%%v"
if not defined CN_PIN echo .python-version is missing from this folder. Download Context Notes again.
if not defined CN_PIN goto :fail
set "CN_NODOT=%CN_PIN:.=%"
set "CN_LOCAL=%LOCALAPPDATA%\Programs\Python\Python%CN_NODOT%\python.exe"
set "CN_MANAGER=%LOCALAPPDATA%\Python\pythoncore-%CN_PIN%-64\python.exe"

if not exist ".venv\Scripts\python.exe" goto :setup
".venv\Scripts\python.exe" make_venv.py --ready >nul 2>&1 && goto :start

:setup
echo Getting Context Notes ready to run. This happens once, after an update or the first time.
echo It takes a few minutes. Leave this window open.
echo.
call :find_python
if not defined CN_SETUP call :install_python
if not defined CN_SETUP goto :fail
%CN_SETUP% make_venv.py --yes
if errorlevel 1 goto :setup_failed
".venv\Scripts\python.exe" make_venv.py --ready
if errorlevel 1 goto :setup_failed
echo.
echo All set. Starting Context Notes...
echo.

:start
call ".venv\Scripts\activate.bat"
rem Keep python.exe here, not pythonw.exe: the app needs a console.
python app.py
echo.
echo The app has stopped. Press any key to close this window.
pause >nul
exit /b 0

:setup_failed
echo.
echo Setting up didn't finish. The lines above say why. Send a photo of this window to whoever gave you the app.

:fail
echo.
echo Press any key to close this window.
pause >nul
exit /b 1

rem ---- the Python that makes .venv: python.org's installer, its install manager, else the py launcher
:find_python
set "CN_SETUP="
if exist "%CN_LOCAL%" set CN_SETUP="%CN_LOCAL%"
if defined CN_SETUP exit /b 0
if exist "%CN_MANAGER%" set CN_SETUP="%CN_MANAGER%"
if defined CN_SETUP exit /b 0
where py >nul 2>&1 || exit /b 0
py -%CN_PIN% -c "import sys" >nul 2>&1 && set "CN_SETUP=py -%CN_PIN%"
exit /b 0

:install_python
echo Context Notes needs Python %CN_PIN%, which isn't on this computer.
where winget >nul 2>&1
if errorlevel 1 goto :python_by_hand
choice /c YN /m "Install Python %CN_PIN% now? It's free, from python.org, and takes a minute or two"
if errorlevel 2 goto :python_by_hand
winget install --exact --id Python.Python.%CN_PIN% --scope user --accept-package-agreements --accept-source-agreements
call :find_python
if defined CN_SETUP exit /b 0
echo.
echo Python %CN_PIN% didn't install. The lines above say why.

:python_by_hand
echo.
echo Install Python %CN_PIN% from the page that's opening now: pick "Python %CN_PIN%" (not a newer one),
echo download the Windows installer, run it, then double-click Context Notes again.
start "" "https://www.python.org/downloads/windows/"
exit /b 0
