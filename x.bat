@echo off
setlocal EnableExtensions EnableDelayedExpansion
title KBMTI Dev Testing
color 0B

:: Always run from the folder containing this BAT file
cd /d "%~dp0"

cls
echo.
echo  ============================================================
echo.
echo       K   K  B B B  M   M  T T T  I
echo       K  K   B   B  MM MM    T    I
echo       KKK    B B B  M M M    T    I
echo       K  K   B   B  M   M    T    I
echo       K   K  B B B  M   M    T    I
echo.
echo                    Dev Testing
echo.
echo  ============================================================
echo.

call :progress "Initializing KBMTI Dev Testing" 3
call :progress "Compiling startup environment" 3

echo.
echo  [BOOT] Starting backend...
call :progress "Preparing backend" 2

if not exist "backend\.venv\Scripts\activate.bat" (
    color 0C
    echo.
    echo  [ERROR] Virtual environment was not found:
    echo          %~dp0backend\.venv\
    echo.
    echo  Please check that backend\.venv exists.
    pause
    exit /b 1
)

echo.
echo  [VENV] Activating backend virtual environment...
call "backend\.venv\Scripts\activate.bat"
if errorlevel 1 (
    color 0C
    echo.
    echo  [ERROR] Could not activate backend virtual environment.
    pause
    exit /b 1
)

call :progress "Loading Python environment" 2

echo.
echo  [READY] Virtual environment activated.
echo  [RUN]   python -m kbmti
echo.
call :progress "Starting KBMTI" 2

echo.
echo  ============================================================
echo                  KBMTI IS STARTING
echo  ============================================================
echo.

python -m kbmti

echo.
echo  [EXIT] KBMTI process has ended.
echo.
pause
exit /b

:progress
set "message=%~1"
set /a "steps=%~2"
<nul set /p "=[ .. ] %message%"
for /L %%i in (1,1,%steps%) do (
    <nul set /p "=."
    timeout /t 1 /nobreak >nul
)
echo  [OK]
exit /b
