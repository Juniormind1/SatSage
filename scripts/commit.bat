@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM SatSage: commit without AI. Repo root = parent of scripts\
REM Maintainer-only: identity MUST be Juniormind1 <juniormind@proton.me>
REM Other contributors: use normal git with their own identity.
REM
REM Usage:
REM   scripts\commit.bat "Commit-Message"
REM   scripts\commit.bat -u "tracked only"
REM   scripts\commit.bat -A "all including binary untracked"
REM   scripts\commit.bat --staged "index only"
REM   scripts\commit.bat --fix-identity "Message"

cd /d "%~dp0.."
set "REQUIRED_NAME=Juniormind1"
set "REQUIRED_EMAIL=juniormind@proton.me"
set "ADD_MODE=auto"
set "FIX_IDENTITY=0"
set "MSG="

:parse
if "%~1"=="" goto after_parse
if /i "%~1"=="-h" goto usage
if /i "%~1"=="--help" goto usage
if /i "%~1"=="-u" (
  set "ADD_MODE=-u"
  shift
  goto parse
)
if /i "%~1"=="-A" (
  set "ADD_MODE=-A"
  shift
  goto parse
)
if /i "%~1"=="--all" (
  set "ADD_MODE=-A"
  shift
  goto parse
)
if /i "%~1"=="--staged" (
  set "ADD_MODE=staged"
  shift
  goto parse
)
if /i "%~1"=="--fix-identity" (
  set "FIX_IDENTITY=1"
  shift
  goto parse
)
if defined MSG (
  echo Nur eine Commit-Message erlaubt.
  exit /b 2
)
set "MSG=%~1"
shift
goto parse

:after_parse
if not defined MSG (
  echo Commit-Message fehlt.
  goto usage
)

if "%FIX_IDENTITY%"=="1" (
  git config user.name "%REQUIRED_NAME%"
  git config user.email "%REQUIRED_EMAIL%"
  git config core.hooksPath githooks
  echo Identitaet + hooksPath gesetzt.
)

set "NAME="
set "EMAIL="
set "HOOKS="
for /f "delims=" %%A in ('git config --get user.name 2^>nul') do set "NAME=%%A"
for /f "delims=" %%A in ('git config --get user.email 2^>nul') do set "EMAIL=%%A"
for /f "delims=" %%A in ('git config --get core.hooksPath 2^>nul') do set "HOOKS=%%A"

if /i not "%NAME%"=="%REQUIRED_NAME%" goto bad_id
if /i not "%EMAIL%"=="%REQUIRED_EMAIL%" goto bad_id
goto id_ok

:bad_id
echo ERROR: Maintainer-Commit nur als %REQUIRED_NAME% ^<%REQUIRED_EMAIL%^>.
echo   Contributor mit eigener ID: normales git commit, nicht dieses Skript.
echo   scripts\commit.bat --fix-identity "deine Message"
exit /b 1

:id_ok
if /i not "%HOOKS%"=="githooks" (
  echo WARN: core.hooksPath ist '%HOOKS%' ^(erwartet: githooks^).
  echo   git config core.hooksPath githooks
)

echo === status ^(vorher^) ===
git status -sb
if errorlevel 1 exit /b 1

if /i "%ADD_MODE%"=="staged" goto after_add
if /i "%ADD_MODE%"=="-A" (
  git add -A
  if errorlevel 1 exit /b 1
  goto after_add
)
if /i "%ADD_MODE%"=="-u" (
  git add -u
  if errorlevel 1 exit /b 1
  goto after_add
)

REM ADD_MODE=auto: tracked + untracked text; binary asks
git add -u
if errorlevel 1 exit /b 1
call :stage_untracked_smart
if errorlevel 1 exit /b 1

:after_add
git diff --cached --quiet
if not errorlevel 1 (
  echo Nichts gestaged - Abbruch.
  git status -sb
  exit /b 1
)

echo === staged ===
git diff --cached --stat

git commit -m "%MSG%"
if errorlevel 1 exit /b 1

echo === HEAD ===
git log -1 --format="%%h %%an <%%ae>%%n%%s"
git status -sb
echo Push: scripts\push.bat
exit /b 0

:usage
echo Usage: scripts\commit.bat [-u^|-A^|--staged] [--fix-identity] "Message"
echo   Default: tracked + untracked text; binary untracked prompts.
exit /b 2

:stage_untracked_smart
set "_UT_LIST="
for /f "delims=" %%F in ('git ls-files --others --exclude-standard 2^>nul') do set "_UT_LIST=1"
if not defined _UT_LIST exit /b 0

echo === untracked ===
for /f "delims=" %%F in ('git ls-files --others --exclude-standard 2^>nul') do (
  call :handle_untracked "%%F"
  if errorlevel 1 exit /b 1
)
exit /b 0

:handle_untracked
set "UF=%~1"
call :is_binary "%UF%"
if errorlevel 1 goto handle_text

set "ANS="
set /p "ANS=Binaer untracked stagen? %UF% [j/N] "
if /i "!ANS!"=="j" goto bin_yes
if /i "!ANS!"=="y" goto bin_yes
if /i "!ANS!"=="ja" goto bin_yes
if /i "!ANS!"=="yes" goto bin_yes
echo   uebersprungen ^(Binaer^): %UF%
exit /b 0

:bin_yes
git add -- "%UF%"
if errorlevel 1 exit /b 1
echo   gestaged ^(Binaer, bestaetigt^): %UF%
exit /b 0

:handle_text
git add -- "%UF%"
if errorlevel 1 exit /b 1
echo   gestaged ^(Text^): %UF%
exit /b 0

REM errorlevel 0 = binary, 1 = text
:is_binary
set "BF=%~1"
set "EXT="
for %%E in ("%BF%") do set "EXT=%%~xE"
if defined EXT set "EXT=!EXT:~1!"
if defined EXT (
  for %%E in (
    exe dll so dylib o a png jpg jpeg gif webp ico bmp pdf zip gz tgz bz2 xz 7z rar
    bin s9pk pyc pyo whl egg wasm woff woff2 ttf otf mp3 mp4 mov avi sqlite db
    dmg iso class jar pak dat npy pkl pt onnx
  ) do if /i "!EXT!"=="%%E" exit /b 0
)

py -c "import sys; p=open(sys.argv[1],'rb').read(8192); sys.exit(0 if b'\x00' in p else 1)" "%BF%" 2>nul
if errorlevel 2 exit /b 1
if errorlevel 1 exit /b 1
exit /b 0
