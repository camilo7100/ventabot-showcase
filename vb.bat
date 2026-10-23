@echo off
REM ==========================================================================
REM  VentaBot - atajos para Windows (equivalente al Makefile de Linux/macOS)
REM
REM  Uso:   vb <comando>
REM  Ej.:   vb preflight
REM
REM  Antes de usarlo, activa el entorno:   .venv\Scripts\activate.bat
REM ==========================================================================
setlocal

if "%~1"=="" goto :help
if /I "%~1"=="help"         goto :help
if /I "%~1"=="setup"        goto :setup
if /I "%~1"=="init-env"     goto :initenv
if /I "%~1"=="test"         goto :test
if /I "%~1"=="lia"          goto :lia
if /I "%~1"=="golden"       goto :golden
if /I "%~1"=="ojos"         goto :ojos
if /I "%~1"=="medios"       goto :medios
if /I "%~1"=="trazas"       goto :trazas
if /I "%~1"=="metricas"     goto :metricas
if /I "%~1"=="repasar"      goto :repasar
if /I "%~1"=="verdad"       goto :verdad
if /I "%~1"=="charla"       goto :charla
if /I "%~1"=="ventas"       goto :ventas
if /I "%~1"=="respaldo"     goto :respaldo
if /I "%~1"=="reiniciar"    goto :reiniciar
if /I "%~1"=="diagnostico"  goto :diagnostico
if /I "%~1"=="chatwoot"     goto :chatwoot
if /I "%~1"=="ensayo"       goto :ensayo
if /I "%~1"=="prueba-chatwoot" goto :prueba_chatwoot
if /I "%~1"=="webhook"       goto :webhook
if /I "%~1"=="ver-todo"     goto :vertodo
if /I "%~1"=="erp"          goto :erp
if /I "%~1"=="fletes"       goto :fletes
if /I "%~1"=="muestrario"   goto :muestrario
if /I "%~1"=="marketing"    goto :marketing
if /I "%~1"=="hablar"       goto :hablar
if /I "%~1"=="panel"        goto :panel
if /I "%~1"=="plantillas"   goto :plantillas
if /I "%~1"=="recordatorios" goto :recordatorios
if /I "%~1"=="retomar" goto :retomar
if /I "%~1"=="banco" goto :banco
if /I "%~1"=="anuncios" goto :anuncios
if /I "%~1"=="asignar"      goto :asignar
if /I "%~1"=="demo"         goto :demo
if /I "%~1"=="server"       goto :server
if /I "%~1"=="simular"      goto :simular
if /I "%~1"=="f1-check"     goto :f1check
if /I "%~1"=="firma"        goto :firma
if /I "%~1"=="app"          goto :app
if /I "%~1"=="token"        goto :token
if /I "%~1"=="webhooks"     goto :webhooks
if /I "%~1"=="conexion"     goto :conexion
if /I "%~1"=="registrar"    goto :registrar
if /I "%~1"=="preflight"    goto :preflight
if /I "%~1"=="ollama-check" goto :ollamacheck
if /I "%~1"=="ollama-setup" goto :ollamasetup
if /I "%~1"=="lint"         goto :lint
if /I "%~1"=="fmt"          goto :fmt
if /I "%~1"=="types"        goto :types
if /I "%~1"=="arch"         goto :arch
if /I "%~1"=="check"        goto :check
if /I "%~1"=="clean"        goto :clean

echo Comando desconocido: %~1
echo.
goto :help

:help
echo.
echo   VentaBot - comandos disponibles
echo.
echo     vb setup          Crea el entorno .venv con uv e instala todo
echo     vb init-env       Crea el archivo .env (y genera el token de Meta)
echo     vb preflight      Dice que falta para cerrar la Fase 0
echo     vb ollama-setup   Configura Ollama para GPU de 4 GB (una sola vez)
echo     vb ollama-check   Criterio de aceptacion de la Fase 0
echo     vb test           Corre los tests (deben pasar en ~1 segundo)
echo     vb demo           Una venta completa en la terminal, sin internet
echo.
echo   FASE 1 - el bot escuchando de verdad
echo     vb server         Arranca el servidor (deja ESTA ventana ocupada)
echo     vb simular        Manda mensajes de prueba (en OTRA ventana)
echo     vb f1-check       Examen de la Fase 1 (con el servidor corriendo)
echo     vb firma          Diagnostica un 403 "firma invalida" de Meta
echo     vb lia            La venta de Lia completa, en 2 segundos
echo     vb golden         Mide si el modelo entiende, con un numero
echo     vb ojos           Prueba el lector de imagenes con fotos reales
echo     vb medios         Dice por que no salen las fotos y los videos
echo     vb trazas         Comprueba que LangSmith esta grabando
echo     vb metricas       Capas de IA, escaladas, historial, costo y latencia
echo     vb repasar        Repasa las conversaciones reales y las puntua
echo     vb verdad         La prueba de verdad: clientas con la IA real, en el servidor
echo     vb charla         Un mensaje como clienta al bot real, aislado (--conv x --texto "...")
echo     vb ventas         Actualiza el Excel de ventas (--abrir para abrirlo)
echo     vb respaldo       Copia la base y el Excel (--listar para ver las copias)
echo     vb reiniciar      Borra las charlas de prueba (respalda antes)
echo     vb diagnostico    REVISA TODO de punta a punta y dice como quedo
echo     vb chatwoot       Levanta el CRM en tu PC y lo conecta
echo     vb ensayo         Ensaya WhatsApp-bot-Chatwoot de punta a punta (gratis)
echo     vb prueba-chatwoot  Lia contesta desde Chatwoot y sale a WhatsApp de verdad
echo     vb webhook --ver    A donde manda Meta los mensajes (--apuntar URL / --quitar)
echo     vb erp            El ERP en Google Sheets (--sincronizar / --montar / --importar-sabana X.xlsx)
echo     vb fletes         Tabla de envios: vb fletes / vb fletes cali / --revisar
echo     vb muestrario     Mide el color de cada circon en la foto (--hoja X.png)
echo     vb marketing      Que revision del marketing hay (--instalar ARCHIVO la pone)
echo     vb hablar         Conversa con el bot desde la terminal
echo     vb panel          Enciende el panel del taller y da el enlace
echo     vb ver-todo       Abre el CENTRO DE MANDO: todo en una pagina
echo     vb plantillas     Plantillas de WhatsApp: como van y que pegar
echo     vb recordatorios  A quien le toca un recordatorio y cuando (no manda nada)
echo     vb retomar        Clientas con mensaje atrasado sin respuesta (--enviar: plantilla)
echo     vb banco          Banco de plantillas por situacion: estado, limpiar (--borrar), sincronizar
echo     vb anuncios       De que anuncios llegan clientas al bot (--horas 6)
echo     vb asignar        Cada charla de Chatwoot asignada a quien la atiende (--aplicar)
echo     vb app            Dice de que app de Meta es tu secreto
echo     vb token          Comprueba el token de Meta y como renovarlo
echo     vb registrar      Activa el numero en Meta (los 2 pasos que faltan)
echo     vb conexion       Revisa la cadena Meta - ngrok - tu servidor
echo     vb webhooks       Que webhooks han llegado de Meta y que paso con cada uno
echo.
echo     vb lint           Revisa el estilo del codigo
echo     vb fmt            Formatea y arregla el estilo
echo     vb types          Revisa los tipos
echo     vb arch           Verifica la arquitectura hexagonal
echo     vb check          Todo lo anterior (lo mismo que corre CI)
echo     vb clean          Borra archivos temporales
echo.
goto :eof

:initenv
python scripts\init_env.py %2
goto :eof

:setup
echo.
REM Desde septiembre de 2026 VentaBot NO usa conda: un .venv con uv dentro
REM del repo. Se borra borrando la carpeta y no ensucia nada mas.
echo   Creando el entorno .venv con uv y Python 3.11...
if not exist .venv\Scripts\activate.bat call uv venv --python 3.11 || goto :error
call .venv\Scripts\activate.bat
echo.
echo   Instalando dependencias (esto tarda 1-3 minutos)...
call uv pip install -r requirements-dev.txt || goto :error
echo.
if not exist .env python scripts\init_env.py
echo.
echo   LISTO. Ahora, EN ESTA MISMA VENTANA, corre:
echo.
echo       .venv\Scripts\activate.bat
echo       vb preflight
echo.
goto :eof

:ollamasetup
echo.
echo   Configurando Ollama para una GPU de 4 GB de VRAM...
echo.
setx OLLAMA_CONTEXT_LENGTH 16000 >nul
setx OLLAMA_FLASH_ATTENTION 1    >nul
setx OLLAMA_KV_CACHE_TYPE q8_0   >nul
setx OLLAMA_NUM_PARALLEL 1       >nul
setx OLLAMA_KEEP_ALIVE 30m       >nul
echo   Variables guardadas:
echo     OLLAMA_CONTEXT_LENGTH = 16000   (evita el desborde silencioso de 4K)
echo     OLLAMA_FLASH_ATTENTION = 1      (menos memoria al crecer el contexto)
echo     OLLAMA_KV_CACHE_TYPE = q8_0     (la mitad de memoria de cache)
echo     OLLAMA_NUM_PARALLEL = 1         (menos varianza = mas determinismo)
echo     OLLAMA_KEEP_ALIVE = 30m         (no recargar el modelo a cada rato)
echo.
echo   AHORA HAZ ESTO, O NO SIRVE DE NADA:
echo     1. Busca el icono de Ollama abajo a la derecha, junto al reloj.
echo        (puede estar escondido bajo la flechita ^)
echo     2. Clic derecho sobre el -^> Quit Ollama
echo     3. Abre Ollama otra vez desde el menu Inicio
echo     4. CIERRA esta ventana y abre una nueva
echo.
echo   Luego verifica con:   ollama ps
echo.
goto :eof

:test
python -m pytest tests/ -m "not integracion"
goto :eof

:demo
python scripts\demo_conversacion.py
goto :eof

:server
echo.
echo   Arrancando el servidor. Esta ventana se queda ocupada: es normal.
echo   Para probarlo, abre OTRA ventana, activa el .venv y corre:  vb simular
echo   Para pararlo: Ctrl+C
echo.
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload
goto :eof

:simular
python scripts\simular_whatsapp.py %2 %3 %4 %5 %6 %7 %8 %9
goto :eof

:f1check
python scripts\f1_check.py
goto :eof

:firma
python scripts\diagnostico_firma.py %2 %3 %4
goto :eof

:lia
python scripts\demo_lia.py
goto :eof

:golden
python scripts\golden.py %2 %3
goto :eof

:ojos
python scripts\ojos.py %2 %3 %4
goto :eof

:medios
python scripts\medios.py
goto :eof

:trazas
python scripts\trazas.py
goto :eof

:metricas
python scripts\metricas.py %2 %3 %4 %5
goto :eof

:repasar
python scripts\repasar.py %2 %3 %4 %5
goto :eof

:verdad
rem La prueba de verdad corre EN EL SERVIDOR, aislada: scripts\prueba_de_verdad.py
ssh servidor-demo "cd ~/ventabot && sudo docker compose run --rm --no-deps -T ventabot python scripts/prueba_de_verdad.py %2 %3"
goto :eof

:charla
rem Un turno de charla de prueba con la IA real, EN EL SERVIDOR y aislado
rem (base temporal, sin WhatsApp ni Chatwoot): scripts\charla.py
ssh servidor-demo "mkdir -p /tmp/charlas_prueba && chmod 777 /tmp/charlas_prueba && cd ~/ventabot && sudo docker compose run --rm --no-deps -T -v /tmp/charlas_prueba:/tmp/charlas_prueba ventabot python scripts/charla.py %2 %3 %4 %5 %6 %7"
goto :eof

:ventas
python scripts\ventas.py %2 %3
goto :eof

:respaldo
python scripts\respaldo.py %2
goto :eof

:reiniciar
python scripts\reiniciar_chats.py %2 %3
goto :eof

:diagnostico
python scripts\diagnostico.py %2 %3
goto :eof

:fletes
python scripts\fletes.py %2 %3 %4
goto :eof

:muestrario
python scripts\medir_muestrario.py %2 %3
goto :eof

:marketing
python scripts\marketing.py %2 %3
goto :eof

:chatwoot
python scripts\chatwoot.py %2
goto :eof

:ensayo
python scripts\ensayo_chatwoot.py
goto :eof

:prueba_chatwoot
python scripts\prueba_desde_chatwoot.py
goto :eof

:webhook
python scripts\webhook_meta.py %2 %3
goto :eof

:vertodo
python scripts\ver_todo.py %2
goto :eof

:erp
python scripts\erp.py %2 %3
goto :eof

:hablar
python scripts\conversar.py %2 %3
goto :eof

:panel
python scripts\panel_token.py %2
goto :eof

:plantillas
python scripts\plantillas.py %2
goto :eof

:asignar
rem En el SERVIDOR: deja cada conversacion asignada a VentaBot o a la persona
rem que la atiende. Sin --aplicar solo muestra que haria. No escribe a nadie.
rem En el PC: python scripts\asignar_conversaciones.py (lee la base local).
ssh servidor-demo "cd ~/ventabot && sudo docker compose exec -T ventabot python scripts/asignar_conversaciones.py %2"
goto :eof

:recordatorios
rem Lee la base del SERVIDOR (la de verdad). Con --plantilla crea la de Meta.
rem En el PC: python scripts\recordatorios.py (lee la base local).
ssh servidor-demo "cd ~/ventabot && sudo docker compose exec -T ventabot python scripts/recordatorios.py %2"
goto :eof

:retomar
rem Las clientas con un mensaje ATRASADO de Meta (mas de 24 h) que nadie
rem contesto. Con --enviar les manda la plantilla de emergencia (16/10).
rem En el PC: python scripts\retomar_atrasadas.py (lee la base local).
ssh servidor-demo "cd ~/ventabot && sudo docker compose exec -T ventabot python scripts/retomar_atrasadas.py %2"
goto :eof

:banco
rem El banco de plantillas por situacion (22/10): `vb banco estado` dice cuales
rem aprobo Meta por grupo; `vb banco limpiar` muestra que sobra (con --borrar
rem guarda la lista y borra). Corre en el servidor.
rem En el PC: python scripts\banco_de_plantillas.py estado (con el token local).
ssh servidor-demo "cd ~/ventabot && sudo docker compose exec -T ventabot python scripts/banco_de_plantillas.py %2 %3"
goto :eof

:anuncios
rem De que anuncios le llegan clientas al bot. Tras lanzar una campana, a
rem las 2-3 h cada anuncio del bot tiene que salir aqui (ADR 0030).
rem En el PC: python scripts\anuncios.py (lee la base local).
ssh servidor-demo "cd ~/ventabot && sudo docker compose exec -T ventabot python scripts/anuncios.py %2 %3"
goto :eof

:app
python scripts\app_meta.py %2 %3
goto :eof

:token
python scripts\token_meta.py %2
goto :eof

:webhooks
python scripts\webhooks.py %2 %3
goto :eof

:conexion
python scripts\conexion.py
goto :eof

:registrar
python scripts\registrar_numero.py %2 %3
goto :eof

:preflight
python scripts\preflight.py
goto :eof

:ollamacheck
python scripts\f0_determinismo.py
goto :eof

:lint
ruff check app tests scripts
goto :eof

:fmt
ruff check --fix app tests scripts
ruff format app tests scripts
goto :eof

:types
mypy app/domain app/graph
goto :eof

:arch
lint-imports
goto :eof

:check
call :lint  || goto :error
call :types || goto :error
call :arch  || goto :error
call :test  || goto :error
echo.
echo   TODO EN VERDE.
goto :eof

:clean
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
if exist .pytest_cache rd /s /q .pytest_cache
if exist .ruff_cache   rd /s /q .ruff_cache
if exist .mypy_cache   rd /s /q .mypy_cache
echo   Limpio.
goto :eof

:error
echo.
echo   ALGO FALLO. Lee el mensaje de arriba.
exit /b 1
