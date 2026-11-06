@echo off
cd /d "%~dp0"
rem Preferuj Python 3.14 x64, ale zachowaj zgodność ze środowiskami 3.13.
py -3.14 -c "import sys" >nul 2>&1
if not errorlevel 1 goto python314
py -3.13 -c "import sys" >nul 2>&1
if not errorlevel 1 goto python313
goto missing_python

:python314
py -3.14 start_bot.py
if errorlevel 1 pause
exit /b

:python313
py -3.13 start_bot.py
if errorlevel 1 pause
exit /b

:missing_python
echo Nie znaleziono Pythona 3.14 ani 3.13 x64.
echo Zainstaluj Python 3.14 x64 i zaleznosci:
echo   winget install -e --id Python.Python.3.14 --architecture x64
echo   py -3.14 -m pip install -r requirements.txt
pause
exit /b 1
