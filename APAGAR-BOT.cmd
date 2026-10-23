@echo off
rem ==========================================================================
rem  APAGAR VENTABOT - cierra las dos ventanas que abrio ENCENDER-BOT.cmd.
rem  Mientras este apagado, los mensajes que lleguen al numero del negocio
rem  NO se contestan (Meta los guarda un rato, pero nadie responde).
rem ==========================================================================
chcp 65001 >nul
echo.
echo   Apagando VentaBot...
rem Se busca por el comando que corre, no por el titulo: el titulo de la
rem ventana cambia en cuanto arranca el programa y taskkill no la encuentra.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'servidor-en-bucle|tunel\.cmd|uvicorn app.api.main|ngrok(\.exe)?\S*\s+(http|start)|VENTABOT - ' -and $_.Name -ne 'powershell.exe' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }"
timeout /t 3 /nobreak >nul
echo   Listo: el bot esta apagado.
echo.
if "%~1"=="--silencioso" goto :eof
timeout /t 5 >nul
