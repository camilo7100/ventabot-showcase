@echo off
rem ==========================================================================
rem  CONECTAR CHATWOOT CON EL BOT - doble clic, despues de crear tu usuario
rem  en Chatwoot. Crea el buzon, el webhook y ajusta el .env; luego reinicia
rem  el bot para que lo tome.
rem ==========================================================================
chcp 65001 >nul
cd /d "%~dp0"
title VentaBot - conectando Chatwoot
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe scripts\chatwoot.py --conectar
if errorlevel 1 (
    echo.
    echo   No se pudo conectar. Lee el mensaje de arriba.
    pause
    exit /b 1
)
echo   Reiniciando el bot para que tome la conexion...
call "%~dp0APAGAR-BOT.cmd"
start "" "%~dp0ENCENDER-BOT.cmd"
echo.
echo   Listo. Esta ventana se cierra sola.
timeout /t 10 >nul
