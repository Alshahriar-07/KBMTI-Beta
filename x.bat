@echo off
setlocal EnableExtensions EnableDelayedExpansion
title KBMTI Dev Testing
color 0A

:: ================= SETTINGS =================
:: Set to 1 to skip the whole intro animation
set "SKIP_INTRO=0"
:: ============================================

:: Always run from the folder containing this BAT file
cd /d "%~dp0"

:: ---------- Quick check before animation ----------
if not exist "backend\.venv\Scripts\activate.bat" (
    color 0C
    echo.
    echo  [ERROR] Virtual environment was not found:
    echo          %~dp0backend\.venv\
    echo.
    pause
    exit /b 1
)

set "hex=0123456789ABCDEF"
for /f %%a in ('"prompt $H & for %%b in (1) do rem"') do set "BS=%%a"

if "%SKIP_INTRO%"=="1" goto :launch

:: =====================================================
:: PHASE 1 - NETWORK / PORT SCAN (~6s)
:: =====================================================
cls
color 0A
echo.
echo  [ PHASE 1/6 ]  NETWORK SURFACE SCAN
echo  ------------------------------------------------------------
for /L %%n in (1,1,36) do (
    set /a p=!random! %% 65535 + 1
    set "pp=     !p!"
    set /a s=!random! %% 5
    if !s!==0 (set "st=OPEN      ") else if !s!==1 (set "st=FILTERED  ") else (set "st=CLOSED    ")
    echo   [SCAN] 127.0.0.1:!pp:~-5!   !st!  ttl=!random:~-2!
    call :ms 150
)

:: =====================================================
:: PHASE 2 - KEY DECRYPT CASCADE (~6s)
:: =====================================================
cls
color 0E
echo.
echo  [ PHASE 2/6 ]  DECRYPTING ACCESS KEY
echo  ------------------------------------------------------------
set "target=KBMTI-DEV-ACCESS-A7F3C9E1"
for /L %%i in (0,1,24) do (
    set /a rest=24-%%i
    set "head=!target:~0,%%i!"
    set "tail="
    if !rest! gtr 0 call :rh !rest! tail
    echo   [DECRYPT] !head!!tail!   locked %%i/24
    call :ms 220
)
echo.
echo   [KEY] Access key verified.
call :ms 600

:: =====================================================
:: PHASE 3 - MEMORY DUMP (~6s)
:: =====================================================
cls
color 0A
echo.
echo  [ PHASE 3/6 ]  MEMORY SEGMENT DUMP
echo  ------------------------------------------------------------
for /L %%n in (1,1,30) do (
    call :rh 8 addr
    set "bytes="
    for /L %%j in (1,1,8) do (
        call :rh 2 b
        set "bytes=!bytes!!b! "
    )
    call :rh 16 asc
    echo   0x!addr!  !bytes! !asc!
    call :ms 180
)

:: =====================================================
:: PHASE 4 - MODULE INTEGRITY CHECK (~6s)
:: =====================================================
cls
color 0B
echo.
echo  [ PHASE 4/6 ]  MODULE INTEGRITY CHECK
echo  ------------------------------------------------------------
for %%m in (core backend api database auth scheduler logger watchdog cache queue config models) do (
    set "n=%%m               "
    <nul set /p "=  [CHECK] !n:~0,12! "
    call :ms 280
    call :rh 16 h
    echo sha:!h!  [ PASS ]
    call :ms 250
)

:: =====================================================
:: PHASE 5 - SECURE TUNNEL WITH SPINNER (~7s)
:: =====================================================
cls
color 0A
echo.
echo  [ PHASE 5/6 ]  ESTABLISHING SECURE TUNNEL
echo  ------------------------------------------------------------
echo.
call :spin "Resolving local host                "
call :spin "Handshake with backend              "
call :spin "Negotiating encrypted channel       "
call :spin "Injecting runtime environment       "
call :spin "Syncing configuration               "

:: =====================================================
:: PHASE 6 - ACCESS GRANTED + LOGO (~4s)
:: =====================================================
cls
color 0B
echo.
echo  ============================================================
echo                       ACCESS  GRANTED
echo  ============================================================
echo.
echo       K   K  B B B  M   M  T T T  I
echo       K  K   B   B  MM MM    T    I
echo       KKK    B B B  M M M    T    I
echo       K  K   B   B  M   M    T    I
echo       K   K  B B B  M   M    T    I
echo.
echo                  [ DEV TESTING MODE ]
echo.
echo  ============================================================
echo.
<nul set /p "=  [LAUNCH] ["
for /L %%i in (1,1,40) do (
    <nul set /p "=#"
    call :ms 70
)
echo ] 100%%
echo.
call :ms 400

:: =====================================================
:: LAUNCH
:: =====================================================
:launch
call "backend\.venv\Scripts\activate.bat"
if errorlevel 1 (
    color 0C
    echo.
    echo  [ERROR] Could not activate backend virtual environment.
    pause
    exit /b 1
)

echo  ============================================================
echo                      KBMTI IS STARTING
echo  ============================================================
echo.

python -m kbmti

echo.
echo  [EXIT] KBMTI process has ended.
echo.
pause
exit /b

:: ---------------- helpers ----------------

:: Accurate delay in milliseconds
:ms
ping 192.0.2.1 -n 1 -w %~1 >nul
exit /b

:: Random hex string. Usage: call :rh LENGTH VARNAME
:rh
set "_o="
for /L %%j in (1,1,%~1) do (
    set /a _r=!random! %% 16
    for %%h in (!_r!) do set "_o=!_o!!hex:~%%h,1!"
)
set "%~2=!_o!"
exit /b

:: Spinner line. Usage: call :spin "text"
:spin
<nul set /p "=  [LINK] %~1 "
for /L %%k in (1,1,4) do (
    for %%c in ("/" "-" "\" "|") do (
        <nul set /p "=%%~c!BS!"
        call :ms 90
    )
)
echo [ OK ]
exit /b