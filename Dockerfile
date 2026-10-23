# VentaBot en un contenedor: lo mismo que corre en el portátil, listo para un
# servidor en la nube que no se apaga.
#
#   docker compose up -d --build        (ver docker-compose.yml)
#
# Tres reglas, y por qué:
#   1. Nada secreto adentro. Las claves llegan del .env al ARRANCAR, no se hornean
#      en la imagen (ver .dockerignore): una imagen se copia y se sube.
#   2. Los datos viven en un volumen (/app/estado): la base con los pedidos, las
#      fotos que sube Lía y el Excel. Reconstruir la imagen no borra un pedido.
#   3. Corre como un usuario sin privilegios. Si alguien encuentra un fallo en el
#      webhook, no es root del servidor.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Bogota

# curl: para el chequeo de salud. tzdata: la hora de Colombia en registros y avisos.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Primero las dependencias: si solo cambia el código, esta capa se reutiliza y
# reconstruir tarda segundos en vez de minutos.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 ventabot \
    && mkdir -p /app/estado /app/data/renders /app/logs \
    && chown -R ventabot:ventabot /app/estado /app/data/renders /app/logs
USER ventabot

# Dónde viven los datos que no se pueden perder.
ENV SQLITE_PATH=/app/estado/ventabot.db \
    VENTAS_EXCEL=/app/estado/Ventas_LunaJoyas.xlsx \
    RESPALDOS_DIR=/app/estado/respaldos

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
