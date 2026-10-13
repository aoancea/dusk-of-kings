@echo off
REM Builds a standalone Windows version of Dusk of Kings into dist\DuskOfKings\
REM Run from the project folder after installing requirements:  pip install -r requirements.txt pyinstaller
setlocal
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)

%PY% -m PyInstaller --noconfirm --clean --windowed --name DuskOfKings ^
  --add-data "data;data" ^
  --collect-all ursina ^
  --collect-all panda3d ^
  --collect-all direct ^
  --exclude-module tkinter ^
  --exclude-module matplotlib ^
  main.py
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)
echo.
echo Done. Run dist\DuskOfKings\DuskOfKings.exe
endlocal
