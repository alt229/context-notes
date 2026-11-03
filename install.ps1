# Installs Context Notes on Windows, from nothing. In PowerShell (no administrator needed):
#
#     irm https://raw.githubusercontent.com/alt229/context-notes/master/install.ps1 | iex
#
# It installs what's missing with winget (Git, Python as pinned in .python-version, ffmpeg, and after a yes VLC and
# Claude Code), downloads Context Notes to %USERPROFILE%\context-notes (or updates it if it's there), puts the
# "Context Notes" and "Update Context Notes" shortcuts on the desktop, and starts the app, whose launcher
# (context-notes.bat) makes the .venv. Run it again any time: it skips what's already there.
# Run from inside a downloaded copy, it uses that folder instead. Created 2026-11-02.

$ErrorActionPreference = 'Stop'
$Repo = 'https://github.com/alt229/context-notes.git'

function Say($text) { Write-Host $text -ForegroundColor Cyan }
function Warn($text) { Write-Host $text -ForegroundColor Yellow }

function Stop-Install($text) {
    Write-Host ''
    Write-Host $text -ForegroundColor Red
    Write-Host 'Send a photo of this window to whoever gave you the app.'
    Read-Host 'Press Enter to close' | Out-Null
    exit 1
}

function Ask($question) {
    $answer = Read-Host "$question [Y/n]"
    return ($answer -eq '' -or $answer -match '^[Yy]')
}

# A program winget just installed isn't on this window's PATH yet: read it again from the registry.
function Update-Path {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

function Found($command, $places) {
    if (Get-Command $command -ErrorAction SilentlyContinue) { return $true }
    foreach ($p in $places) { if ($p -and (Test-Path $p)) { return $true } }
    return $false
}

function Install($name, $id) {
    Say "Installing $name..."
    & winget install --exact --id $id --scope user --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        # Some packages have no per-user installer: try again for the whole computer (Windows may ask to allow it).
        & winget install --exact --id $id --silent --accept-package-agreements --accept-source-agreements
    }
    Update-Path
}

Write-Host ''
Say 'Context Notes: installing. This takes a few minutes the first time. Leave this window open.'
Write-Host ''

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Start-Process 'ms-windows-store://pdp/?productid=9NBLGGH4NNS1'
    Stop-Install ('This needs winget ("App Installer"), which is missing. The Microsoft Store is opening on it: ' +
                  'install or update it, then run this again.')
}

# ---- Git, then the code
if (-not (Found 'git' @("$env:ProgramFiles\Git\cmd\git.exe", "$env:LOCALAPPDATA\Programs\Git\cmd\git.exe"))) {
    Install 'Git' 'Git.Git'
    foreach ($p in @("$env:LOCALAPPDATA\Programs\Git\cmd", "$env:ProgramFiles\Git\cmd")) {
        if ((Test-Path "$p\git.exe") -and -not (Get-Command git -ErrorAction SilentlyContinue)) { $env:Path += ";$p" }
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Stop-Install "Git didn't install. The lines above say why." }
}

if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'app.py'))) {
    $Folder = $PSScriptRoot
    Say "Using the copy in $Folder"
} else {
    $Folder = Join-Path $env:USERPROFILE 'context-notes'
    if (Test-Path (Join-Path $Folder '.git')) {
        Say "Context Notes is already in $Folder. Getting the latest version..."
        & git -C $Folder pull --ff-only
        if ($LASTEXITCODE -ne 0) { Warn "Couldn't update it (the lines above say why). Carrying on with the copy that's there." }
    } elseif (Test-Path $Folder) {
        Stop-Install "$Folder is already there but isn't a Context Notes download. Rename or move it, then run this again."
    } else {
        Say "Downloading Context Notes to $Folder..."
        & git clone $Repo $Folder
        if ($LASTEXITCODE -ne 0) { Stop-Install "The download didn't work. The lines above say why." }
    }
}

# ---- Python, the version in .python-version (the launcher makes the .venv with it)
$Pin = (Get-Content (Join-Path $Folder '.python-version') -TotalCount 1).Trim()
$NoDot = $Pin.Replace('.', '')
$PythonPlaces = @("$env:LOCALAPPDATA\Programs\Python\Python$NoDot\python.exe",
                  "$env:LOCALAPPDATA\Python\pythoncore-$Pin-64\python.exe",
                  "$env:ProgramFiles\Python$NoDot\python.exe")
$HavePython = $false
foreach ($p in $PythonPlaces) { if (Test-Path $p) { $HavePython = $true } }
if (-not $HavePython -and (Get-Command py -ErrorAction SilentlyContinue)) {
    try { & py "-$Pin" -c 'import sys' 2>$null; $HavePython = ($LASTEXITCODE -eq 0) } catch { $HavePython = $false }
}
if (-not $HavePython) { Install "Python $Pin" "Python.Python.$Pin" }

# ---- ffmpeg (the app reads the films with it)
$WingetLinks = "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffmpeg.exe"
if (-not (Found 'ffmpeg' @($WingetLinks))) {
    Install 'ffmpeg' 'Gyan.FFmpeg'
    if (-not (Found 'ffmpeg' @($WingetLinks))) { Warn "ffmpeg didn't install. Try later in PowerShell: winget install Gyan.FFmpeg" }
}

# ---- VLC (to watch with the notes), optional
$VlcPlaces = @("$env:ProgramFiles\VideoLAN\VLC\vlc.exe", "${env:ProgramFiles(x86)}\VideoLAN\VLC\vlc.exe")
if (-not (Found 'vlc' $VlcPlaces)) {
    if (Ask 'Install VLC, the player that shows the notes?') { Install 'VLC' 'VideoLAN.VLC' }
}

# ---- Claude Code (writes the notes on a Claude plan), optional
$ClaudePlaces = @("$env:USERPROFILE\.local\bin\claude.exe", "$env:LOCALAPPDATA\Microsoft\WinGet\Links\claude.exe")
if (-not (Found 'claude' $ClaudePlaces)) {
    if (Ask 'Install Claude Code, which writes the notes on a Claude plan (you sign in later, in the app''s Settings)?') {
        Install 'Claude Code' 'Anthropic.ClaudeCode'
    }
}

# ---- shortcuts, then start (context-notes.bat makes the .venv the first time)
Write-Host ''
& cmd /c "`"$Folder\make-shortcut.bat`" --no-pause"
Write-Host ''
Say 'Installed. Starting Context Notes: the first start sets it up, which takes a few minutes.'
Say 'Next time, double-click "Context Notes" on your desktop.'
Start-Process -FilePath (Join-Path $Folder 'context-notes.bat') -WorkingDirectory $Folder
