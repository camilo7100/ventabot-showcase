@echo off
rem ==========================================================================
rem  REINICIAR PRUEBAS - doble clic para empezar de cero con tus numeros.
rem
rem  Borra EN EL SERVIDOR, solo para los numeros de config\numeros-de-prueba.txt:
rem    - la conversacion y lo que el bot recuerda de ella,
rem    - la ficha de la clienta y sus pedidos,
rem    - su contacto en Chatwoot, con sus conversaciones.
rem  Las clientas de verdad NO se tocan. El ERP de Google Sheets tampoco.
rem
rem  Antes de borrar se hace un respaldo en el servidor.
rem  Para agregar un numero de prueba: edita config\numeros-de-prueba.txt.
rem ==========================================================================
chcp 65001 >nul
cd /d "%~dp0"
title VentaBot - reiniciar numeros de prueba
setlocal enabledelayedexpansion

set "LISTA="
for /f "usebackq eol=# tokens=1" %%n in ("config\numeros-de-prueba.txt") do (
    if defined LISTA (set "LISTA=!LISTA!,%%n") else (set "LISTA=%%n")
)
if not defined LISTA (
    echo.
    echo   No hay numeros en config\numeros-de-prueba.txt
    echo.
    pause
    exit /b 1
)

echo.
echo   Se van a reiniciar estos numeros de prueba, en el servidor:
echo.
for %%n in (%LISTA:,= %) do echo       %%n
echo.
echo   Su conversacion, su ficha, sus pedidos y su contacto en Chatwoot
echo   quedan en cero. Las clientas de verdad no se tocan.
echo.
choice /c SN /n /m "  Continuar? [S/N] "
if errorlevel 2 (
    echo.
    echo   Cancelado. No se toco nada.
    echo.
    timeout /t 5 >nul
    exit /b 0
)

echo.
ssh -o BatchMode=yes -o ConnectTimeout=30 servidor-demo "cd ~/ventabot && sudo docker compose exec -T -e PYTHONIOENCODING=utf-8 ventabot python scripts/reiniciar_chats.py --si --numeros %LISTA%"
if errorlevel 1 (
    echo.
    echo   ******************************************************************
    echo   No se pudo reiniciar. Arriba dice por que. Pideme ayuda.
    echo   ******************************************************************
    echo.
    pause
    exit /b 1
)
echo.
echo   Listo: escribe desde esos numeros y el bot empieza de cero.
echo.
pause
