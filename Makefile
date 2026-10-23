# ===========================================================================
# VentaBot — atajos. Corre `make` para ver todo.
# ===========================================================================
.DEFAULT_GOAL := help
.PHONY: help setup init-env install test test-cov lint fmt types arch check demo preflight \
        ollama-check ollama-setup server simular f1-check firma app token lia golden ojos medios trazas metricas repasar verdad charla ventas respaldo reiniciar diagnostico chatwoot ensayo prueba-chatwoot webhook ver-todo erp fletes muestrario marketing hablar panel plantillas recordatorios retomar banco anuncios webhooks conexion registrar up down logs clean

help:  ## Muestra esta ayuda
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	 | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup:  ## Crea el venv, instala todo y activa pre-commit
	python3 -m venv .venv
	./.venv/bin/pip install --upgrade pip
	./.venv/bin/pip install -r requirements-dev.txt
	./.venv/bin/pre-commit install
	./.venv/bin/python scripts/init_env.py
	@echo ""
	@echo "  Listo. Activa el entorno con:  source .venv/bin/activate"

init-env:  ## Crea el archivo .env desde .env.example (genera el token de Meta)
	python3 scripts/init_env.py

install:  ## Solo instala dependencias
	pip install -r requirements-dev.txt

test:  ## Corre los tests rápidos (sin integración)
	pytest tests/ -m "not integracion"

test-cov:  ## Tests con reporte de cobertura del dominio
	pytest tests/ -m "not integracion" --cov=app/domain --cov=app/graph \
	       --cov-report=term-missing

lint:  ## Ruff
	ruff check app tests scripts

fmt:  ## Formatea y arregla lo que se pueda
	ruff check --fix app tests scripts
	ruff format app tests scripts

types:  ## mypy sobre el dominio (lo que más importa que esté bien tipado)
	mypy app/domain app/graph

arch:  ## Verifica que la arquitectura hexagonal no se haya roto
	lint-imports

check: lint types arch test  ## Todo lo que corre CI

preflight:  ## Valida los requisitos de la Fase 0 y dice qué falta
	python3 scripts/preflight.py

ollama-check:  ## Comprueba Ollama + determinismo del NLU (criterio de Fase 0)
	python3 scripts/f0_determinismo.py

ollama-setup:  ## Arranca Ollama con el perfil de poca VRAM (deja la terminal ocupada)
	OLLAMA_CONTEXT_LENGTH=16000 OLLAMA_FLASH_ATTENTION=1 \
	OLLAMA_KV_CACHE_TYPE=q8_0 OLLAMA_NUM_PARALLEL=1 OLLAMA_KEEP_ALIVE=30m \
	ollama serve

demo:  ## Una venta completa en la terminal, sin red
	python3 scripts/demo.py

server:  ## Arranca el servidor (ocupa la terminal)
	python3 -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --reload

simular:  ## Manda un mensaje de prueba: make simular M="hola"
	python3 scripts/simular_whatsapp.py $(M)

registrar:  ## Activa el número en Meta (register + subscribed_apps)
	python3 scripts/registrar_numero.py

conexion:  ## Revisa la cadena Meta → ngrok → tu servidor
	python3 scripts/conexion.py

webhooks:  ## Qué webhooks han llegado de Meta y qué pasó con cada uno
	python3 scripts/webhooks.py

firma:  ## Diagnostica un 403 "firma inválida" de Meta
	python3 scripts/diagnostico_firma.py $(A)

app:  ## Dice de qué app de Meta es tu App Secret
	python3 scripts/app_meta.py $(A)

lia:  ## La venta de Lía completa, sin red ni LLM
	python3 scripts/demo_lia.py

golden:  ## Mide si el modelo entiende, con un numero
	python3 scripts/golden.py $(A)

ojos:  ## Prueba el lector de imagenes con fotos reales
	python3 scripts/ojos.py $(A)

medios:  ## Dice por que no salen las fotos y los videos
	python3 scripts/medios.py

trazas:  ## Comprueba que LangSmith esta grabando
	python3 scripts/trazas.py

metricas:  ## Capas de IA, escaladas, historial, costo y latencia
	python3 scripts/metricas.py $(A)

repasar:  ## Repasa las conversaciones reales y las puntua
	python3 scripts/repasar.py $(A)

verdad:  ## La prueba de verdad: clientas con la IA real, aislada (en el servidor)
	python3 scripts/prueba_de_verdad.py $(A)

charla:  ## Un mensaje como clienta al bot real, aislado (A='--conv x --texto hola')
	python3 scripts/charla.py $(A)

ventas:  ## Actualiza el Excel de ventas (A=--abrir para abrirlo)
	python3 scripts/ventas.py $(A)

respaldo:  ## Copia la base y el Excel (A=--listar para ver las copias)
	python3 scripts/respaldo.py $(A)

reiniciar:  ## Borra las charlas de prueba (respalda antes; A=--si)
	python3 scripts/reiniciar_chats.py $(A)

diagnostico:  ## REVISA TODO de punta a punta y dice como quedo (A=--rapido)
	python3 scripts/diagnostico.py $(A)

chatwoot:  ## Levanta el CRM en tu PC y lo conecta
	python3 scripts/chatwoot.py $(A)

ensayo:  ## Ensaya WhatsApp-bot-Chatwoot de punta a punta (gratis)
	python3 scripts/ensayo_chatwoot.py

prueba-chatwoot:  ## Lía contesta desde Chatwoot y sale a WhatsApp de verdad
	python3 scripts/prueba_desde_chatwoot.py

webhook:  ## A donde manda Meta los mensajes (ARGS="--apuntar URL" o "--quitar")
	python3 scripts/webhook_meta.py $(or $(ARGS),--ver)

ver-todo:  ## Abre el CENTRO DE MANDO: todo lo que controla el negocio
	python3 scripts/ver_todo.py $(A)

erp:  ## El ERP en Google Sheets: make erp / A=--sincronizar / A=--montar
	python3 scripts/erp.py $(A)

fletes:  ## Tabla de envios: make fletes / make fletes A=cali / A=--revisar
	python3 scripts/fletes.py $(A)

muestrario:  ## Mide el color de cada circon en la foto: make muestrario / A="--hoja X.png"
	python3 scripts/medir_muestrario.py $(A)

marketing:  ## Que revision del marketing hay: make marketing / A="--instalar ARCHIVO"
	python3 scripts/marketing.py $(A)

hablar:  ## Conversa con el bot desde la terminal
	python3 scripts/conversar.py $(A)

panel:  ## Enciende el panel del taller y da el enlace
	python3 scripts/panel_token.py $(A)

plantillas:  ## Plantillas de WhatsApp: como van y que pegar en Meta
	python3 scripts/plantillas.py $(A)

asignar:  ## Cada charla de Chatwoot asignada a quien la atiende (A=--aplicar)
	python3 scripts/asignar_conversaciones.py $(A)

recordatorios:  ## A quien le toca un recordatorio y cuando, sin mandar nada (A=--plantilla)
	python3 scripts/recordatorios.py $(A)

retomar:  ## Clientas con mensaje atrasado sin respuesta (A=--enviar: la plantilla)
	python3 scripts/retomar_atrasadas.py $(A)

banco:  ## Banco de plantillas: estado | limpiar [--borrar] (A='estado')
	python3 scripts/banco_de_plantillas.py $(A)

anuncios:  ## De que anuncios llegan clientas al bot (A='--horas 6')
	python3 scripts/anuncios.py $(A)

token:  ## Comprueba el token de Meta y explica cómo renovarlo
	python3 scripts/token_meta.py $(A)

f1-check:  ## Examen de la Fase 1 (con el servidor corriendo en otra terminal)
	python3 scripts/f1_check.py

up:  ## Levanta el bot en Docker, como en el servidor (se reinicia solo si se cae)
	docker compose up -d --build
	docker compose ps

down:  ## Baja el bot de Docker (los datos del volumen se quedan)
	docker compose down

logs:  ## Sigue lo que hace el bot dentro de Docker
	docker compose logs -f ventabot

clean:  ## Borra cachés
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov
