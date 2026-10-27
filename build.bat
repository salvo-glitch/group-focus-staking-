@echo off
setlocal
cd /d "%~dp0"

echo.
echo === Preparazione ambiente di compilazione ===
py -m pip install --upgrade pip
if errorlevel 1 goto errore
py -m pip install pyinstaller pillow
if errorlevel 1 goto errore

echo.
echo === Creazione eseguibile Windows ===
py -m PyInstaller --noconfirm --clean --onefile --console --name RaggruppaFocusStack --collect-all PIL raggruppa_focus_stack.py
if errorlevel 1 goto errore

echo.
echo Eseguibile creato in:
echo %~dp0dist\RaggruppaFocusStack.exe
echo.
pause
exit /b 0

:errore
echo.
echo Si e' verificato un errore. Controlla i messaggi qui sopra.
pause
exit /b 1
