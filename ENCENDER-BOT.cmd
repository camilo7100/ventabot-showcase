@echo off
rem ==========================================================================
rem  ENCENDER VENTABOT - doble clic y listo.
rem
rem  Prende TODO: Docker con Chatwoot (el CRM de Lía), el bot y el tunel.
rem  Abre DOS ventanas que tienen que quedarse abiertas mientras el bot atiende:
rem    1. "VentaBot - SERVIDOR"  : el bot. Aqui ves cada mensaje que entra y
rem                                 lo que responde.
rem    2. "VentaBot - TUNEL"     : ngrok, el puente entre internet y tu PC (el bot
rem       y Chatwoot con https por el mismo dominio: ver ngrok.yml).
rem  Si cierras cualquiera de las dos, el bot deja de contestar.
rem  Para apagar todo: doble clic en APAGAR-BOT.cmd
rem
rem  Al final SIEMPRE corre el diagnostico (scripts\diagnostico.py): revisa
rem  el bot, el tunel, Chatwoot, las credenciales, la base, el ERP y los logs,
rem  y saca una ventanita diciendo si quedo todo bien o que quedo roto.
rem  Encender sin saber si el tunel y el CRM quedaron arriba es no encender.
rem ==========================================================================
chcp 65001 >nul
cd /d "%~dp0"
title VentaBot - encendiendo

set "PUBLIC_URL="
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if "%%a"=="PUBLIC_URL" set "PUBLIC_URL=%%b"
)
if "%PUBLIC_URL%"=="" (
    echo.
    echo   No encontre PUBLIC_URL en el archivo .env
    echo   Sin eso Meta no sabe a donde mandar los mensajes.
    pause
    exit /b 1
)

rem Desde el 25/09 el bot atiende desde el servidor (Oracle), no desde este PC.
rem Este PC es el PLAN B: solo arranca si el servidor NO responde (o con
rem ENCENDER-BOT.cmd --forzar). Si arranca por eso, al final le dice a Meta que
rem entregue aqui (scripts\webhook_meta.py --quitar).
set "PRODUCCION=https://bot.lunajoyas.example"
set "NUBE="
for /f %%c in ('curl -s -o nul -m 15 -w "%%{http_code}" "%PRODUCCION%/health" 2^>nul') do set "NUBE=%%c"
curl -s -o nul -m 3 http://127.0.0.1:8000/health >nul 2>&1
if not errorlevel 1 set "NUBE=este-pc"
if "%NUBE%"=="200" if /i not "%~1"=="--forzar" (
    echo.
    echo   ==================================================================
    echo   El bot YA esta atendiendo desde el servidor en la nube ^(Oracle^).
    echo   No hace falta prender nada en este PC.
    echo.
    echo   Este archivo es el PLAN B: usalo solo si el servidor se cae.
    echo   ==================================================================
    echo.
    pause
    exit /b 0
)

echo.
rem Apagar ANTES de encender. Si quedó un servidor de la vez pasada, el
rem nuevo no puede tomar el puerto 8000 y se queda reiniciandose en
rem bucle: el bot sigue contestando, pero con el codigo viejo. Paso el
rem 20/09 y costo una hora de pruebas que no probaban nada.
echo   Cerrando lo que hubiera quedado abierto...
call "%~dp0APAGAR-BOT.cmd" --silencioso
echo.
rem Chatwoot vive en Docker y Docker tarda en prender: va PRIMERO, para que
rem cuando el bot arranque, su CRM ya lo este esperando.
call "%~dp0scripts\encender-docker.cmd"
echo.
echo   Encendiendo VentaBot...
echo.
start "VentaBot - SERVIDOR" cmd /k scripts\servidor-en-bucle.cmd

rem El tunel arranca cuando el servidor ya responde.
timeout /t 8 /nobreak >nul
start "VentaBot - TUNEL" cmd /k scripts\tunel.cmd

timeout /t 6 /nobreak >nul
echo   Listo. Quedaron abiertas dos ventanas: SERVIDOR y TUNEL.
echo.
rem PLAN B: el servidor no respondio, asi que Meta tiene que entregar aqui.
rem Quitar la direccion de produccion hace que Meta vuelva al webhook de la
rem app, que es este ngrok. Cuando el servidor vuelva, SUBIR-A-GITHUB.cmd (o
rem scripts\webhook_meta.py --apuntar) la pone otra vez.
if not "%NUBE%"=="200" if not "%NUBE%"=="este-pc" (
    echo   El servidor no responde: Meta va a entregar los mensajes a ESTE PC.
    .venv\Scripts\python.exe scripts\webhook_meta.py --quitar
    echo.
)
echo   Revisando que TODO haya quedado conectado...
echo.
.venv\Scripts\python.exe scripts\diagnostico.py --rapido --ventana
echo.
echo   Para probar: desde tu WhatsApp personal escribele al numero del negocio.
echo   En la ventana SERVIDOR vas a ver "entra:" con tu mensaje y lo que respondio.
echo.
echo   Esta ventana se cierra sola en 20 segundos.
timeout /t 20 >nul
