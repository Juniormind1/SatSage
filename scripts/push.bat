@echo off
setlocal EnableExtensions
REM SatSage: push current branch to origin (without AI).
REM Maintainer-only: config AND tip author must be Juniormind1 <juniormind@proton.me>
REM Other contributors: use normal git push with their own identity.
REM
REM Usage:
REM   scripts\push.bat
REM   scripts\push.bat --fix-identity

cd /d "%~dp0.."
set "REQUIRED_NAME=Juniormind1"
set "REQUIRED_EMAIL=juniormind@proton.me"

if /i "%~1"=="--fix-identity" (
  git config user.name "%REQUIRED_NAME%"
  git config user.email "%REQUIRED_EMAIL%"
  git config core.hooksPath githooks
  echo Identitaet + hooksPath gesetzt.
)

set "NAME="
set "EMAIL="
for /f "delims=" %%A in ('git config --get user.name 2^>nul') do set "NAME=%%A"
for /f "delims=" %%A in ('git config --get user.email 2^>nul') do set "EMAIL=%%A"

if /i not "%NAME%"=="%REQUIRED_NAME%" goto bad_id
if /i not "%EMAIL%"=="%REQUIRED_EMAIL%" goto bad_id
goto id_ok

:bad_id
echo ERROR: Maintainer-Push nur als %REQUIRED_NAME% ^<%REQUIRED_EMAIL%^>.
echo   Contributor mit eigener ID: normales git push, nicht dieses Skript.
echo   scripts\push.bat --fix-identity
exit /b 1

:id_ok
set "BRANCH="
for /f "delims=" %%B in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%B"
if /i "%BRANCH%"=="HEAD" (
  echo ERROR: detached HEAD - kein Push.
  exit /b 1
)

set "TIP_NAME="
set "TIP_EMAIL="
for /f "delims=" %%A in ('git log -1 --format^=%%an') do set "TIP_NAME=%%A"
for /f "delims=" %%A in ('git log -1 --format^=%%ae') do set "TIP_EMAIL=%%A"
if /i not "%TIP_NAME%"=="%REQUIRED_NAME%" goto bad_tip
if /i not "%TIP_EMAIL%"=="%REQUIRED_EMAIL%" goto bad_tip
goto tip_ok

:bad_tip
echo ERROR: Tip-Autor ist %TIP_NAME% ^<%TIP_EMAIL%^> - Maintainer-Push verweigert.
echo   Erwartet: %REQUIRED_NAME% ^<%REQUIRED_EMAIL%^>
echo   z. B. git commit --amend --reset-author --no-edit  ^(nur wenn Tip noch lokal^)
exit /b 1

:tip_ok
set "HOOKS="
for /f "delims=" %%A in ('git config --get core.hooksPath 2^>nul') do set "HOOKS=%%A"
if /i not "%HOOKS%"=="githooks" (
  echo WARN: core.hooksPath='%HOOKS%' ^(erwartet githooks^) - pre-push greift ggf. nicht.
)

echo === push %BRANCH% -^> origin ^(als %REQUIRED_NAME%^) ===
git status -sb
REM Explicit ref (some clones track only main).
git push -u origin "refs/heads/%BRANCH%:refs/heads/%BRANCH%"
if errorlevel 1 exit /b 1

echo === remote tip ===
git ls-remote origin "refs/heads/%BRANCH%"
git status -sb
git log -1 --format="%%h %%an <%%ae> %%s"
exit /b 0
