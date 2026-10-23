@echo off
REM ==========================================================================
REM  VER-TODO — abre el centro de mando de VentaBot en el navegador.
REM
REM  Ahi esta todo: el taller, las conversaciones, Chatwoot, el ERP, el
REM  registro y como va cada pieza ahora mismo.
REM
REM  El token se lee del .env al vuelo: no esta escrito en este archivo.
REM ==========================================================================
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo.
  echo   No encuentro el entorno .venv. Corre primero:  vb setup
  echo.
  pause
  exit /b 1
)

.venv\Scripts\python.exe scripts\ver_todo.py %1
if errorlevel 1 pause
