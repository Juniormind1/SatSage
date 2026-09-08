@echo off
REM Baut die SatSage-Web-GUI als Windows-Standalone (PyInstaller Onefile).
setlocal EnableExtensions
cd /d "%~dp0\.."

set "PY="
if defined PYTHON (
  set "PY=%PYTHON%"
) else if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  where py >nul 2>&1
  if not errorlevel 1 (
    set "PY=py"
  ) else (
    set "PY=python"
  )
)

echo → Python: %PY%
"%PY%" -c "import sys; print('  ', sys.version.split()[0], sys.platform)"
if errorlevel 1 (
  echo Fehler: Python nicht gefunden. PYTHON setzen oder py/python im PATH.
  exit /b 1
)

echo → Abhaengigkeiten (requirements + pyinstaller + Pillow fuer Splash^)…
"%PY%" -m pip install -q -r requirements.txt "pyinstaller>=6.0" "Pillow>=9.0"
if errorlevel 1 exit /b 1

echo → Marke und Splash (sat-logo + SatSage final^)…
"%PY%" scripts\prepare_brand_assets.py
if errorlevel 1 exit /b 1
"%PY%" scripts\make_splash.py
if errorlevel 1 exit /b 1

echo → PyInstaller (Onefile + Splash^)…
if exist "build\satsage-webgui" rmdir /s /q "build\satsage-webgui"
if exist "dist\satsage-webgui.exe" del /f /q "dist\satsage-webgui.exe"
"%PY%" -m PyInstaller --noconfirm --clean packaging\satsage-webgui.spec
if errorlevel 1 exit /b 1

if not exist "dist\satsage-webgui.exe" (
  echo Fehler: dist\satsage-webgui.exe nicht erzeugt.
  exit /b 1
)

if exist ".env.example" copy /y ".env.example" "dist\.env.example" >nul

echo.
echo Fertig.
echo   Binary : %CD%\dist\satsage-webgui.exe
echo   Splash : packaging\satsage-splash.png (Logo beim Start^)
echo   Start  : dist\satsage-webgui.exe
echo   Config : .env neben der EXE anlegen (Vorlage: dist\.env.example^)
echo   Caches : utxo_cache\ und immutable_cache\ entstehen neben der EXE
exit /b 0
