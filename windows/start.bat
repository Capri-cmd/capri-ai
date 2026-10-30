@echo off
rem Capri on Windows, from source. First run: makes a Python environment in .venv and installs the packages
rem (PySide6, numpy, sound, OCR; no torch). Then she starts; her brain, ears and voice download from her
rem right-click menu.
rem   start.bat           start her
rem   start.bat --setup   pick and download everything in this window instead
cd /d "%~dp0.."
rem .venv\installed.txt is written only once every package is in (a closed or failed install resumes next time)
if exist .venv\installed.txt goto run
if exist .venv\Scripts\python.exe goto install
set "PY="
for %%v in (3.12 3.11 3.10 3.13) do if not defined PY py -%%v -c "" >nul 2>nul && set "PY=py -%%v"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
echo Making the Python environment ...
%PY% -m venv .venv || goto fail
:install
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
echo Installing packages (a few minutes the first time) ...
.venv\Scripts\python.exe -m pip install -r portable\requirements.txt || goto fail
rem her cloned voice; --no-deps: its Chinese extra won't build without a compiler, and the rest is in requirements
.venv\Scripts\python.exe -m pip install --no-deps genie-tts==2.0.2 || goto fail
echo ok> .venv\installed.txt
:run
rem her brain, ears and voice download from her right-click menu; start.bat --setup still asks in this window
if /i "%1"=="--setup" (
  .venv\Scripts\python.exe -m capri.setup_cli --setup
  if errorlevel 2 goto :eof
)
start "" .venv\Scripts\pythonw.exe capri_dev.py
goto :eof
:nopython
echo Capri needs Python 3.10-3.13 (64-bit): https://www.python.org/downloads/
pause
exit /b 1
:fail
echo Setup failed.
pause
exit /b 1
