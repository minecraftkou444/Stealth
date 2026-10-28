@echo off
setlocal
cd /d "%~dp0"
title Build Stealth.

echo ========================================
echo          Stealth. Windows Builder
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher ^(py^) was not found.
  echo Install Python 3.12 or 3.13 x64 and enable the Python launcher.
  pause
  exit /b 1
)

if not exist "Stealth_BuildReady.py" (
  echo ERROR: Stealth_BuildReady.py must be in this folder.
  pause
  exit /b 1
)

if not exist "minecraft_instance.ico" (
  echo ERROR: minecraft_instance.ico must be in this folder.
  pause
  exit /b 1
)

echo [1/4] Installing build dependencies...
py -m pip install --upgrade pip
if errorlevel 1 goto :fail
py -m pip install --upgrade PySide6 requests minecraft-launcher-lib pyinstaller
if errorlevel 1 goto :fail

echo.
echo [2/4] Checking Python syntax...
py -m py_compile "Stealth_BuildReady.py"
if errorlevel 1 goto :fail

echo.
echo [3/4] Building Stealth.exe...
py -m PyInstaller --noconfirm --clean --windowed --onefile --name "Stealth" --icon "minecraft_instance.ico" --collect-all minecraft_launcher_lib "Stealth_BuildReady.py"
if errorlevel 1 goto :fail

if not exist "dist\Stealth.exe" (
  echo ERROR: PyInstaller did not create dist\Stealth.exe.
  goto :fail
)

echo.
echo [4/4] Building installer if Inno Setup is installed...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC (
  "%ISCC%" "Stealth_Setup.iss"
  if errorlevel 1 goto :fail
  echo.
  echo SUCCESS: Output\Stealth_Setup.exe
) else (
  echo Inno Setup compiler was not found.
  echo Install Inno Setup 6, then compile Stealth_Setup.iss.
  echo Stealth.exe is ready at dist\Stealth.exe
)

echo.
echo Build finished.
pause
exit /b 0

:fail
echo.
echo BUILD FAILED. Read the error above and send it back for troubleshooting.
pause
exit /b 1
