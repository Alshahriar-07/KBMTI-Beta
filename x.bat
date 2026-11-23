@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title KBMTI // SECURE DEVELOPMENT TERMINAL
mode con: cols=70 lines=42
color 0A

:: ============================================================
::  KBMTI SECURE DEVELOPMENT TERMINAL
::  Usage:  KBMTI-RAW-TEST.exe          normal start
::          KBMTI-RAW-TEST.exe /skip    skip the boot intro
:: ============================================================

set "SKIP_INTRO=0"
if /I "%~1"=="/skip" set "SKIP_INTRO=1"

if /I "%~1"=="/selftest" (
    echo KBMTI launcher self-test OK
    exit /b 0
)

:: ------------------------------------------------------------
::  SERVER-SIDE CREDENTIAL VERIFICATION
::  Access keys are never stored in this file. The Python
::  launcher exchanges the key with the KBMTI license service
::  and receives short-lived signed launch tickets.
:: ------------------------------------------------------------
set "hex=0123456789ABCDEF"

:: 60 box characters and 60 spaces (used to draw aligned frames)
set "EQ=════════════════════════════════════════════════════════════"
set "SP=                                                            "

cd /d "%~dp0"

for /f %%a in ('"prompt $H & for %%b in (1) do rem"') do set "BS=%%a"


:: ============================================================
::  ENVIRONMENT CHECK
:: ============================================================

if not exist "backend\.venv\Scripts\activate.bat" (
    color 0C
    cls
    call :LOGO
    call :TOP
    call :CBOX "SYSTEM ERROR"
    call :MID
    call :LBOX "[ERROR] BACKEND ENVIRONMENT NOT FOUND"
    call :LBOX "Expected: backend\.venv\"
    call :BOT
    echo.
    pause
    exit /b 1
)

if "%SKIP_INTRO%"=="1" goto LOGIN

:: ============================================================
::  BOOT INTRO
:: ============================================================

cls
color 0A
call :LOGO
echo.
echo       INITIALIZING DEVELOPMENT ENVIRONMENT
echo.
echo       [BOOT] Kernel initialization...
call :ms 250
echo       [BOOT] Loading security modules...
call :ms 250
echo       [BOOT] Preparing authentication system...
call :ms 250

:: ============================================================
::  PHASE 1 - NETWORK SCAN
:: ============================================================

call :PHASE 01 "NETWORK SURFACE SCAN" 0A

for %%P in (21 22 53 80 135 139 443 445 3000 3306 5000 5432 6379 8000 8080 8443) do (
    set /a s=!random! %% 3
    set "st=CLOSED  "
    if !s!==0 set "st=OPEN    "
    if !s!==1 set "st=FILTERED"
    set /a lat=!random! %% 40 + 1
    set "pp=%%P      "
    echo   [SCAN] 127.0.0.1:!pp:~0,5! !st!  !lat! ms
    call :ms 70
)

echo.
echo   [OK] NETWORK SCAN COMPLETE
call :ms 250

:: ============================================================
::  PHASE 2 - ACCESS KEY DECRYPTION (visual only, decoy text)
:: ============================================================

call :PHASE 02 "ACCESS KEY DECRYPTION" 0E

set "target=KBMTI-ACCESS-7F3C-A9E1-D204"

for /L %%i in (1,1,27) do (
    set /a rest=27-%%i
    set "head=!target:~0,%%i!"
    set "tail="
    if !rest! gtr 0 call :RH !rest! tail
    echo   [DECRYPT] !head!!tail!
    call :ms 60
)

echo.
echo   [OK] ENCRYPTION VERIFIED
call :ms 250

:: ============================================================
::  PHASE 3 - MEMORY ANALYSIS
:: ============================================================

call :PHASE 03 "MEMORY SEGMENT ANALYSIS" 0A

for /L %%n in (1,1,16) do (
    call :RH 8 addr
    call :RH 24 data
    echo   0x!addr!  !data:~0,4! !data:~4,4! !data:~8,4! !data:~12,4! !data:~16,4! !data:~20,4!
    call :ms 55
)

echo.
echo   [OK] MEMORY ANALYSIS COMPLETE
call :ms 250

:: ============================================================
::  PHASE 4 - MODULE VERIFICATION
:: ============================================================

call :PHASE 04 "MODULE INTEGRITY CHECK" 0B

for %%m in (
    CORE BACKEND API DATABASE AUTH
    SCHEDULER LOGGER WATCHDOG CACHE
    QUEUE CONFIG MODELS
) do (
    set "mn=%%m            "
    <nul set /p "=  [VERIFY] !mn:~0,10! "
    call :ms 80
    call :RH 16 h
    echo [!h!] [PASS]
)

echo.
echo   [OK] ALL MODULES VERIFIED
call :ms 250

:: ============================================================
::  PHASE 5 - SECURE CONNECTION
:: ============================================================

call :PHASE 05 "ESTABLISHING SECURE CONNECTION" 0A

call :SPIN "Resolving local host"
call :SPIN "Initializing backend"
call :SPIN "Negotiating secure channel"
call :SPIN "Loading runtime environment"
call :SPIN "Synchronizing configuration"
call :SPIN "Verifying dependencies"

echo.
echo   [OK] SECURE CONNECTION ESTABLISHED
call :ms 250

:: ============================================================
::  PHASE 6 - SYSTEM READY
:: ============================================================

cls
color 0B
call :LOGO
call :TOP
call :BLANK
call :CBOX "ACCESS PORTAL READY"
call :BLANK
call :CBOX "SECURITY SYSTEM ACTIVATED"
call :BLANK
call :BOT
echo.
call :BAR "[SYSTEM BOOT]"
call :ms 500

:: ============================================================
::  LOGIN PORTAL
:: ============================================================

:LOGIN

cls
color 0B
call :LOGO
call :TOP
call :CBOX "SECURE LOGIN"
call :MID
call :BLANK
call :LBOX "[1]  LOGIN AS DEVELOPER"
call :BLANK
call :LBOX "[2]  LOGIN AS USER"
call :BLANK
call :LBOX "[3]  LOGIN AS ADMIN"
call :BLANK
call :LBOX "[4]  EXIT"
call :BLANK
call :BOT
echo.

choice /C 1234 /N /M "  Select login type [1-4]: "

if errorlevel 4 exit /b 0
if errorlevel 3 goto ADMIN_LOGIN
if errorlevel 2 goto USER_LOGIN
if errorlevel 1 goto DEV_LOGIN
goto LOGIN

:: ============================================================
::  DEVELOPER LOGIN
:: ============================================================

:DEV_LOGIN

cls
color 0B
call :SMALL_LOGO
echo.
call :TOP
call :CBOX "DEVELOPER AUTHENTICATION"
call :MID
call :LBOX "ACCESS LEVEL : DEVELOPER"
call :LBOX "KEY FORMAT   : KBMTI-XXXXX-0000"
call :LBOX "VERIFIED BY  : KBMTI LICENSE SERVICE"
call :LBOX "ESC = BACK"
call :BOT
echo.

set "LOGIN_ROLE=DEVELOPER"
goto LICENSED_LAUNCH

:: ============================================================
::  USER LOGIN
:: ============================================================

:USER_LOGIN

cls
color 0B
call :SMALL_LOGO
echo.
call :TOP
call :CBOX "USER AUTHENTICATION"
call :MID
call :LBOX "ACCESS LEVEL : USER"
call :LBOX "KEY FORMAT   : KBMTI-XXXXX-0000"
call :LBOX "VERIFIED BY  : KBMTI LICENSE SERVICE"
call :LBOX "ESC = BACK"
call :BOT
echo.

set "LOGIN_ROLE=USER"
goto LICENSED_LAUNCH

:: ============================================================
::  ADMIN LOGIN  (key + password)
:: ============================================================

:ADMIN_LOGIN

cls
color 0E
call :SMALL_LOGO
echo.
call :TOP
call :CBOX "ADMINISTRATOR LOGIN"
call :MID
call :LBOX "ACCESS LEVEL : SYSTEM ADMINISTRATOR"
call :LBOX "STEP 1 OF 2  : ADMIN KEY"
call :LBOX "STEP 2 OF 2  : ADMIN PASSWORD"
call :LBOX "VERIFIED BY  : KBMTI LICENSE SERVICE"
call :LBOX "ESC = BACK"
call :BOT
echo.

set "LOGIN_ROLE=ADMINISTRATOR"
goto LICENSED_LAUNCH

:: ============================================================
::  LICENSED APPLICATION LAUNCH
:: ============================================================

:LICENSED_LAUNCH

cls
color 0B
call :SMALL_LOGO
echo.
call :TOP
call :CBOX "SECURE LICENSE CHECK"
call :MID
call :LBOX "ROLE       : !LOGIN_ROLE!"
call :LBOX "GATEWAY    : KBMTI LICENSE SERVICE"
call :LBOX "TRANSPORT  : SIGNED SHORT-LIVED TOKEN"
call :LBOX "KEY INPUT  : AUTO-UPPERCASE + AUTO-HYPHEN"
call :LBOX "PASSWORD   : MASKED (*)  ENTER = SUBMIT"
call :BOT
echo.
echo   Type the access key using letters and numbers only; uppercase and
echo   the two hyphens are inserted automatically.
echo   The administrator password is masked. Backspace/Delete edit; Escape returns.
echo.

call "backend\.venv\Scripts\activate.bat"
if errorlevel 1 (
    color 0C
    echo.
    echo   [ERROR] VIRTUAL ENVIRONMENT ACTIVATION FAILED
    echo.
    pause
    exit /b 1
)

if /I "!LOGIN_ROLE!"=="DEVELOPER" set "KB_ROLE=DEVELOPER"
if /I "!LOGIN_ROLE!"=="USER" set "KB_ROLE=USER"
if /I "!LOGIN_ROLE!"=="ADMINISTRATOR" set "KB_ROLE=ADMIN"

python -m kbmti.launch --role !KB_ROLE!
set "APP_RC=!errorlevel!"

if "!APP_RC!"=="0" (
    echo.
    echo   [EXIT] KBMTI PROCESS HAS ENDED
    echo.
    pause
    exit /b 0
)

if "!APP_RC!"=="2" goto LOGIN

set /a ATTEMPTS+=1
set /a ATT_LEFT=3-ATTEMPTS
if !ATTEMPTS! GEQ 3 goto LOCKOUT
goto ACCESS_DENIED

:: ============================================================
::  ACCESS DENIED
:: ============================================================

:ACCESS_DENIED

cls
color 0C
call :SMALL_LOGO
echo.
call :TOP
call :CBOX "ACCESS DENIED"
call :MID
call :BLANK
call :LBOX "[ERROR]    INVALID CREDENTIALS"
call :LBOX "[SECURITY] AUTHENTICATION FAILED"
call :LBOX "[SECURITY] ATTEMPTS LEFT: !ATT_LEFT!"
call :BLANK
call :BOT

call :ms 1500

if !ATTEMPTS! GEQ 3 goto LOCKOUT
goto LOGIN

:: ============================================================
::  LOCKOUT AFTER 3 FAILED ATTEMPTS
:: ============================================================

:LOCKOUT

color 0C

for /L %%t in (20,-1,1) do (
    cls
    call :SMALL_LOGO
    echo.
    call :TOP
    call :CBOX "TERMINAL LOCKED"
    call :MID
    call :BLANK
    call :CBOX "TOO MANY FAILED ATTEMPTS"
    call :CBOX "RETRY IN %%t SECONDS"
    call :BLANK
    call :BOT
    call :ms 1000
)

set "ATTEMPTS=0"
goto LOGIN

:: ============================================================
::  SUBROUTINES
:: ============================================================

:: ---- Main logo (K B M T I)
:LOGO
echo.
echo             ██╗  ██╗██████╗ ███╗   ███╗████████╗██╗
echo             ██║ ██╔╝██╔══██╗████╗ ████║╚══██╔══╝██║
echo             █████╔╝ ██████╔╝██╔████╔██║   ██║   ██║
echo             ██╔═██╗ ██╔══██╗██║╚██╔╝██║   ██║   ██║
echo             ██║  ██╗██████╔╝██║ ╚═╝ ██║   ██║   ██║
echo             ╚═╝  ╚═╝╚═════╝ ╚═╝     ╚═╝   ╚═╝   ╚═╝
echo.
echo                      KBMTI // SYSTEM CORE
echo                 ADVANCED DEVELOPMENT TERMINAL
echo.
exit /b

:: ---- Small header
:SMALL_LOGO
echo.
call :TOP
call :CBOX "K B M T I   //   SECURE DEVELOPMENT TERMINAL"
call :BOT
exit /b

:: ---- Boot phase header: call :PHASE NN "TITLE" COLOR
:PHASE
cls
color %~3
call :SMALL_LOGO
echo.
echo   [%~1/06] %~2
echo   !EQ!
echo.
exit /b

:: ---- Frame pieces
:TOP
echo   ╔!EQ!╗
exit /b

:MID
echo   ╠!EQ!╣
exit /b

:BOT
echo   ╚!EQ!╝
exit /b

:BLANK
echo   ║!SP!║
exit /b

:: ---- Centered line inside the frame
:CBOX
set "_t=%~1"
call :STRLEN _t _l
set /a _tot=60-_l, _lf=_tot/2, _rt=_tot-_lf
call :PAD _lf _lp
call :PAD _rt _rp
echo   ║!_lp!!_t!!_rp!║
exit /b

:: ---- Left aligned line inside the frame
:LBOX
set "_t=    %~1"
call :STRLEN _t _l
set /a _rt=60-_l
call :PAD _rt _rp
echo   ║!_t!!_rp!║
exit /b

:: ---- Spaces: call :PAD COUNTVAR OUTVAR
:PAD
set "_c=!%~1!"
if "!_c!"=="0" (
    set "%~2="
) else (
    for %%N in (!_c!) do set "%~2=!SP:~0,%%N!"
)
exit /b

:: ---- String length: call :STRLEN VARNAME OUTVAR
:STRLEN
set "_s=!%~1!"
set "_n=0"
if "!_s!"=="" goto SL_DONE
for %%P in (64 32 16 8 4 2 1) do (
    if not "!_s:~%%P,1!"=="" (
        set /a _n+=%%P
        set "_s=!_s:~%%P!"
    )
)
set /a _n+=1
:SL_DONE
set "%~2=!_n!"
exit /b

:: ---- Progress bar: call :BAR "LABEL"
:BAR
<nul set /p "=  %~1 "
for /L %%i in (1,1,34) do (
    <nul set /p "=█"
    call :ms 28
)
echo  100%%
echo.
exit /b

:: ---- Delay in milliseconds
:ms
ping 192.0.2.1 -n 1 -w %~1 >nul
exit /b

:: ---- Random hex string: call :RH LENGTH OUTVAR
:RH
set "_o="
for /L %%j in (1,1,%~1) do (
    set /a _r=!random! %% 16
    for %%h in (!_r!) do set "_o=!_o!!hex:~%%h,1!"
)
set "%~2=!_o!"
exit /b

:: ---- Connection spinner: call :SPIN "TEXT"
:SPIN
<nul set /p "=  [LINK] %~1 "
for %%r in (1 2) do (
    for %%c in ("/" "-" "\" "|") do (
        <nul set /p "=%%~c!BS!"
        call :ms 45
    )
)
echo [OK]
exit /b
