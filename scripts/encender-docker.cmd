@echo off
rem ==========================================================================
rem  ENCENDER DOCKER Y CHATWOOT  (lo llama ENCENDER-BOT.cmd)
rem
rem  Chatwoot es la bandeja donde Lía responde y ve todo, y corre en Docker.
rem  Antes, Docker habia que prenderlo a mano: el 24/09 el bot quedo arriba
rem  pero sin CRM, y Camilo pidio que un solo doble clic prenda TODO.
rem
rem  Tambien arregla solo la falla del 24/09: Docker Desktop no arranca y
rem  dice "rename ...sock ...sock.stale: El sistema no tiene acceso al
rem  archivo". Son sockets viejos que quedaron trabados; no se pueden borrar,
rem  pero SI se puede apartar la carpeta que los contiene, y Docker la vuelve
rem  a crear limpia.
rem ==========================================================================
setlocal enableextensions
set "DOCKER_EXE=%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin\docker.exe"
if not exist "%DOCKER_EXE%" set "DOCKER_EXE=docker"
set "DOCKER_APP=%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe"
if not exist "%DOCKER_APP%" set "DOCKER_APP=C:\Program Files\Docker\Docker\Docker Desktop.exe"

rem 1. Ya esta el motor? Entonces no se toca nada.
"%DOCKER_EXE%" info >nul 2>&1
if "%errorlevel%"=="0" goto :chatwoot

if not exist "%DOCKER_APP%" (
    echo   [!] No encontre Docker Desktop: Chatwoot no va a arrancar.
    echo       El bot si funciona, pero Lía no vera los chats en el CRM.
    goto :fin
)

echo   Prendiendo Docker (para Chatwoot)...
start "" "%DOCKER_APP%"
call :esperar_motor 18
if "%MOTOR%"=="1" goto :chatwoot

rem 2. No levanto: casi siempre son los sockets trabados. Se apartan y se
rem    reintenta UNA vez.
echo   Docker no levanto. Limpiando archivos viejos que lo traban...
taskkill /f /im "Docker Desktop.exe" >nul 2>&1
taskkill /f /im "com.docker.backend.exe" >nul 2>&1
timeout /t 5 /nobreak >nul
set "SELLO=%DATE:/=-%_%TIME::=-%"
set "SELLO=%SELLO: =%"
if exist "%LOCALAPPDATA%\Docker\run" ren "%LOCALAPPDATA%\Docker\run" "run-viejo-%SELLO%" >nul 2>&1
if exist "%LOCALAPPDATA%\docker-secrets-engine" ren "%LOCALAPPDATA%\docker-secrets-engine" "docker-secrets-engine-viejo-%SELLO%" >nul 2>&1
start "" "%DOCKER_APP%"
call :esperar_motor 18
if "%MOTOR%"=="1" goto :chatwoot

echo   [!] Docker sigue sin arrancar. El bot va a funcionar SIN Chatwoot.
echo       Abrelo a mano y mira que dice la ventana de error.
goto :fin

:chatwoot
echo   Levantando Chatwoot...
"%DOCKER_EXE%" compose -f "%~dp0..\docker\chatwoot\docker-compose.yml" up -d >nul 2>&1
if "%errorlevel%"=="0" (
    echo   Chatwoot arriba.
) else (
    echo   [!] Chatwoot no arranco. El diagnostico de abajo te dice que falta.
)
goto :fin

rem --- espera al motor: %1 intentos de 10 segundos ---------------------------
:esperar_motor
set "MOTOR=0"
for /l %%i in (1,1,%~1) do (
    timeout /t 10 /nobreak >nul
    "%DOCKER_EXE%" info >nul 2>&1
    if not errorlevel 1 (
        set "MOTOR=1"
        goto :eof
    )
)
goto :eof

:fin
endlocal & exit /b 0
