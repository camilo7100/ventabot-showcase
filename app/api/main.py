"""API HTTP: la superficie que ve el mundo exterior.

LAS CUATRO REGLAS DEL WEBHOOK (no negociables)
==============================================
1. Verificar la firma HMAC sobre el BODY CRUDO (bytes). Si parseas el JSON y lo
   vuelves a serializar, la firma NUNCA cuadra. Es el bug nº1 de estas
   integraciones y se pierde medio día en encontrarlo.
2. Usar `hmac.compare_digest`, no `==`. Comparación de tiempo constante.
3. DEDUPLICAR antes de encolar. Meta reintenta; las pasarelas también.
4. Responder 200 en menos de ~200 ms. NADA de inferencia LLM dentro del handler.

En la Fase 1 el trabajo va a `BackgroundTasks`, que corre en el mismo proceso:
suficiente para un servidor y un número de pruebas. En la Fase 6 pasa a una
cola externa (arq + Redis), porque `BackgroundTasks` pierde el trabajo si el
proceso se reinicia a mitad.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.adapters.repositories.webhook_log import registrar
from app.api.panel import router as panel_router
from app.domain.models import Channel, OutboundMessage, new_id
from app.infra.container import ARRANCADO as arrancado_en
from app.infra.container import get_container
from app.infra.logging import configurar
from app.infra.quien_atiende import devolver_al_bot, la_toma_una_persona
from app.infra.settings import get_settings
from app.infra.trazas import activar_desde_settings, traza

log = logging.getLogger("ventabot.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configurar(get_settings().log_level, archivo=get_settings().log_archivo)
    activar_desde_settings(get_settings())
    c = get_container()
    c.dispatcher.arrancar()
    if c.ventas is not None:
        c.ventas.arrancar()
    if c.recordador is not None:
        c.recordador.arrancar()
    if c.vigia is not None:
        c.vigia.arrancar()
    s = c.settings
    log.info("=" * 62)
    log.info("VentaBot escuchando · canal=%s · llm=%s", s.channel_backend, s.llm_backend)
    if s.channel_backend == "console":
        log.info("Las respuestas se IMPRIMEN aquí; no se envían por WhatsApp.")
        log.info('Pruébalo con:  python scripts/simular_whatsapp.py "hola"')

    # Dos avisos que evitan horas de depuración a ciegas: el bot arrancaba
    # tan campante sin poder responder, o firmando con un secreto de mentira.
    if s.usando_secreto_de_desarrollo:
        log.warning(
            "META_APP_SECRET vacío: se firma con el secreto de DESARROLLO. "
            "Meta NUNCA va a coincidir con él."
        )
    # CLIENTAS DE VERDAD CON LOS PEDIDOS EN RAM.
    #
    # `memory` guarda todo en memoria: al parar el servidor se pierden los
    # pedidos, las clientas y el hilo de cada conversación. Es perfecto para la
    # demo y los tests, y es pérdida de datos silenciosa en cuanto el canal es
    # WhatsApp — el bot vende bien, reinicias, y a una clienta que acaba de
    # abonar $60.000 le contesta «todavía no me aparece ningún pedido tuyo».
    #
    # Estaba así en un `.env` de verdad. El aviso va aquí arriba, con los otros
    # que cuestan dinero, y no en un comentario que nadie vuelve a leer.
    if s.channel_backend == "whatsapp" and s.repository_backend == "memory":
        log.error("=" * 62)
        log.error("REPOSITORY_BACKEND=memory CON CLIENTAS DE VERDAD.")
        log.error("Los pedidos viven en RAM: al parar el servidor se pierden TODOS.")
        log.error("Arréglalo antes de vender:   REPOSITORY_BACKEND=sqlite  en el .env")
        log.error("=" * 62)

    if s.channel_backend == "whatsapp" and not s.wa_access_token:
        log.error(
            "WA_ACCESS_TOKEN está VACÍO: el bot podrá RECIBIR mensajes pero "
            "NO podrá responder ninguno."
        )
        log.error(
            "Genéralo en Meta: WhatsApp -> Configuración de la API -> "
            "botón «Generar» junto a Token de acceso."
        )
    # Sin URL pública el bot contesta perfecto y no manda NI UNA foto: ni el
    # muestrario, ni los videos, ni cómo va a quedar su anillo. Es el fallo
    # más silencioso que ha tenido esto, y por eso el aviso va aquí arriba y
    # no enterrado en un WARNING por mensaje.
    if not s.url_publica:
        log.error("NO HAY URL PÚBLICA: el bot NO va a mandar fotos ni videos.")
        log.error("Arréglalo en 10 segundos:   vb panel   (o pon PUBLIC_URL)")
    elif not s.url_publica.startswith("https://"):
        log.error(
            "La URL pública (%s) no es https. Meta solo baja de https.",
            s.url_publica,
        )
    log.info("=" * 62)

    # El token temporal de Meta dura 24 horas. Sin esta comprobación, el
    # servidor arranca verde, recibe mensajes con normalidad y solo falla al
    # RESPONDER — 40 segundos después y en forma de 401 de httpx. Avisar al
    # arrancar convierte "no sé qué pasa" en "renueva el token".
    #
    # Va en segundo plano y con timeout corto a propósito: un problema de red
    # con Meta no puede impedir que el servidor arranque.
    tarea_token = None
    if s.channel_backend == "whatsapp" and s.wa_access_token:
        tarea_token = asyncio.create_task(_avisar_si_el_token_no_sirve(s))

    # Los turnos que ninguna IA pudo contestar se reintentan solos (29/09).
    tarea_reintentos = asyncio.create_task(_reintentar_pendientes(c))
    log.info(
        "si la IA se cae: lo pendiente se reintenta solo (ronda cada %s s)",
        RONDA_DE_REINTENTOS_S,
    )

    # Calentar las capas de modelo en segundo plano: la primera llamada tras
    # arrancar tarda mucho más (compilar el esquema, cargar el modelo) y no la
    # tiene que pagar la primera clienta. No bloquea el arranque.
    #
    # Cada motor sabe calentarse (`calentar()`): el servidor no mira por dentro
    # del bot. Mirar `bot._interprete` tumbó el arranque el día que conversó la
    # asesora, que no tiene intérprete. En LangSmith queda como «calentar_ia»
    # (antes, una traza «modelo» suelta por cada arranque).
    tarea_calentar = None
    calentar = getattr(c.bot, "calentar", None)
    if s.llm_backend in ("claude", "ollama") and callable(calentar):
        tarea_calentar = asyncio.create_task(
            asyncio.to_thread(traza("calentar_ia")(calentar))
        )

    yield
    tarea_reintentos.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarea_reintentos
    if tarea_token:
        tarea_token.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarea_token
    if tarea_calentar and not tarea_calentar.done():
        tarea_calentar.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await tarea_calentar
    # Primero el agrupador: lo que esté esperando ahí todavía no ha pasado por
    # el bot, así que hay que atenderlo ANTES de parar al despachador — si no,
    # su respuesta se quedaría en la outbox sin nadie que la mande.
    if c.agrupador is not None:
        await c.agrupador.detener()
    await c.dispatcher.detener()
    # Lo que se copió a Chatwoot en esos últimos turnos, que llegue antes de
    # salir: Chatwoot es donde Lía y Camilo ven la charla (07/10).
    if c.crm is not None and hasattr(c.crm, "vaciar"):
        await asyncio.to_thread(c.crm.vaciar)
    if c.ventas is not None:
        await c.ventas.detener()
    if c.recordador is not None:
        await c.recordador.parar()
    if c.vigia is not None:
        await c.vigia.detener()


#: Cada cuánto se mira si hay turnos pendientes. Cada uno lleva su propio
#: «próximo intento» (1, 2, 4, 5, 5… minutos): esto es solo la ronda.
RONDA_DE_REINTENTOS_S = 30


async def _reintentar_pendientes(c) -> None:
    """Cada ronda, lo que quedó sin contestar por la IA. Nunca se cae."""
    while True:
        await asyncio.sleep(RONDA_DE_REINTENTOS_S)
        try:
            if c.agrupador is not None:
                await c.agrupador.en_el_hilo(c.reintentar_turnos_pendientes)
            else:
                await asyncio.to_thread(c.reintentar_turnos_pendientes)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("error reintentando los turnos pendientes")


async def _avisar_si_el_token_no_sirve(s) -> None:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as cliente:
            r = await cliente.get(
                f"https://graph.facebook.com/v21.0/{s.wa_phone_number_id}",
                headers={"Authorization": f"Bearer {s.wa_access_token}"},
                params={"fields": "display_phone_number"},
            )
    except Exception:
        return  # sin red no se concluye nada; no se asusta a nadie
    if r.status_code in (401, 403) or r.status_code == 400:
        log.error("=" * 62)
        log.error("EL TOKEN DE META NO SIRVE (caducó o fue revocado).")
        log.error("Vas a RECIBIR mensajes pero no vas a poder responder ninguno.")
        log.error("Arréglalo en 2 minutos:   vb token")
        log.error("=" * 62)


app = FastAPI(title="VentaBot", version="0.1.0", lifespan=lifespan)
app.include_router(panel_router)


def _es_payload_de_ejemplo(cuerpo: bytes) -> bool:
    """El botón «Probar» de Meta manda un ejemplo fijo de su documentación.

    Rechazarlo está bien —nunca se debilita la verificación de firma— pero
    confundirlo con un mensaje real cuesta horas de depuración inútil.
    """
    marcas = (
        b'"id":"0"',
        b'"display_phone_number":"16505551111"',
        b'"body":"this is a text message"',
    )
    return sum(m in cuerpo for m in marcas) >= 2


def _cmd_diagnostico() -> str:
    return "vb firma" if os.name == "nt" else "python3 scripts/diagnostico_firma.py"


def guardar_webhook_fallido(c, raw: bytes, cabeceras: dict):
    """Guarda en disco el webhook cuya firma no cuadró, para poder analizarlo.

    Solo fuera de producción. El cuerpo puede contener el mensaje de un cliente,
    así que en `prod` no se escribe nada: ahí ya no estás depurando.

    NO guarda el secreto. Guarda la firma que MANDÓ Meta (que no es secreta) y
    el cuerpo exacto en bytes, que es lo único con lo que se puede reproducir
    el cálculo.
    """
    if c.settings.entorno == "prod":
        return None
    try:
        destino = c.settings.sqlite_path.parent / "webhook_fallido.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        interesantes = {
            k: v
            for k, v in cabeceras.items()
            if k.lower().startswith(("x-hub", "content-type", "user-agent"))
        }
        destino.write_text(
            json.dumps(
                {
                    "capturado_en": datetime.now(UTC).isoformat(),
                    "cabeceras": interesantes,
                    # HUELLA del secreto que el servidor tenía CARGADO en ese
                    # momento. No es el secreto: es un SHA-256 truncado, y no
                    # se puede volver atrás. Sirve para detectar el caso en
                    # que el .env ya está bien pero el servidor sigue con el
                    # valor viejo porque no se reinició — que por fuera se ve
                    # exactamente igual que un secreto equivocado.
                    "huella_secreto_servidor": hashlib.sha256(
                        c.settings.app_secret_efectivo.encode()
                    ).hexdigest()[:12],
                    # base64 para conservar los BYTES EXACTOS. Guardarlo como
                    # texto podría cambiar un salto de línea y el HMAC ya no
                    # cuadraría: estaríamos depurando un cuerpo distinto.
                    "cuerpo_base64": base64.b64encode(raw).decode(),
                    "cuerpo_bytes": len(raw),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return destino
    except Exception:
        log.exception("no se pudo guardar el webhook fallido")
        return None


@app.get("/media/{nombre}")
def media(nombre: str):
    """Las imágenes del catálogo. Públicas, y tienen que serlo.

    Meta las baja con un GET anónimo desde internet: no puede mandar ningún
    token nuestro. A diferencia de las fotos de los anillos terminados, estas
    NO son datos de nadie — son el muestrario y las fotos de producto, las
    mismas que Lía publica en Instagram. Por eso aquí el nombre puede ser
    legible en vez de treinta y dos caracteres aleatorios.

    Lo que sí se comprueba es que el nombre no se salga de la carpeta:
    `ruta_de_imagen` recorta cualquier `../`.
    """
    from fastapi.responses import FileResponse

    from app.conversacion.salida import ruta_de_media

    c = get_container()
    ruta = ruta_de_media(c.settings.carpetas_de_media, nombre)
    if ruta is None:
        raise HTTPException(status_code=404, detail="not found")
    # El content-type importa: Meta rechaza un video servido como
    # application/octet-stream y el mensaje se queda en la cola sin más
    # explicación que un 400.
    tipos = {".mp4": "video/mp4", ".webp": "image/webp"}
    return FileResponse(
        ruta,
        media_type=tipos.get(ruta.suffix.lower()),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/catalogo/whatsapp.csv", response_class=PlainTextResponse)
def catalogo_de_whatsapp() -> PlainTextResponse:
    """El catálogo del perfil de WhatsApp: Commerce Manager lo lee cada día.

    Público como `/media`: son los precios y las fotos que Lía publica.
    """
    from app.domain.catalogo_meta import catalogo_csv

    c = get_container()
    return PlainTextResponse(
        catalogo_csv(c.products.list_active(), c.settings.url_publica),
        media_type="text/csv; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/health")
def health() -> dict:
    c = get_container()
    return {
        "status": "ok",
        "canal": c.settings.channel_backend,
        "llm": c.settings.llm_backend,
        "repositorio": c.settings.repository_backend,
        "pendientes_en_outbox": len(c.outbox.pending(100)),
        "enviados": c.dispatcher.enviados if c.dispatcher else 0,
        # Desde cuándo lleva vivo ESTE proceso. Sirve para una sola cosa, pero
        # importante: saber si el servidor que contesta es el del código de
        # ahora o uno viejo que se quedó vivo. Pasó el 20/09 — un uvicorn de
        # hacía una hora seguía con el puerto 8000 y el nuevo se reiniciaba en
        # bucle sin poder tomarlo. Todo se veía bien y nada de lo cambiado
        # estaba corriendo.
        "arrancado": ARRANCADO,
    }


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------


#: Cuándo arrancó este proceso, en ISO y UTC. Lo lee `vb diagnostico`.
ARRANCADO = arrancado_en.isoformat(timespec="seconds")


@app.get("/webhook/whatsapp", response_class=PlainTextResponse)
def whatsapp_verify(request: Request) -> str:
    """Handshake que Meta hace UNA vez, al registrar la URL del webhook.

    Meta llama con ?hub.mode=subscribe&hub.verify_token=...&hub.challenge=NNN
    y espera que le devuelvas el `challenge` en texto plano. Si el token no
    coincide con tu META_VERIFY_TOKEN, hay que responder 403.
    """
    c = get_container()
    q = request.query_params
    challenge = c.whatsapp.verify_challenge(
        q.get("hub.mode", ""),
        q.get("hub.verify_token", ""),
        q.get("hub.challenge", ""),
    )
    if challenge is None:
        log.warning("handshake rechazado: verify token no coincide")
        raise HTTPException(status_code=403, detail="verify token inválido")
    log.info("handshake de Meta verificado")
    return challenge


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background: BackgroundTasks,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> dict:
    c = get_container()

    raw = await request.body()  # REGLA 1: bytes crudos, sin parsear
    ruta_log = c.settings.sqlite_path.parent / "webhook_log.jsonl"
    ejemplo = _es_payload_de_ejemplo(raw)

    if not c.whatsapp.verify_signature(raw, x_hub_signature_256 or ""):  # REGLA 2
        registrar(
            ruta_log,
            cuerpo=raw,
            firma_valida=False,
            es_ejemplo=ejemplo,
            nota="rechazado por firma",
        )
        # Guardar el intento fallido es la diferencia entre "adivina qué pasa"
        # y "mídelo". Sin esto, un 403 de firma se depura a ciegas.
        ruta = guardar_webhook_fallido(c, raw, dict(request.headers))
        if _es_payload_de_ejemplo(raw):
            log.warning(
                "firma inválida — pero esto es el payload de EJEMPLO del botón "
                "«Probar» de Meta, no un mensaje real"
            )
            log.warning(
                "escríbele al número de prueba desde tu celular: eso sí prueba algo"
            )
        else:
            log.warning("firma inválida: se descarta el webhook")
        if ruta:
            log.warning("capturado en %s", ruta.name)
            log.warning("diagnostícalo con:  %s", _cmd_diagnostico())
        raise HTTPException(status_code=403, detail="firma inválida")

    from app.domain.catalogo_meta import con_el_producto

    # Si escribe desde un producto del catálogo del perfil, el bot sabe cuál.
    activos = c.products.list_active()
    try:
        leidos = c.whatsapp.parse_webhook(await request.json())
    except Exception:
        # 14/10: un cambio de Meta tumbó esto dos días y NADIE se enteró: las
        # clientas escribían y no entraba nada. Ahora se avisa al celular (y se
        # responde 500: Meta lo reintenta solo hasta por 7 días).
        log.exception("el webhook de WhatsApp no se pudo leer")
        guardar_webhook_fallido(c, raw, dict(request.headers))
        c._avisar(
            "🚨 No están entrando los mensajes de WhatsApp",
            "El bot no pudo leer lo que mandó Meta: las clientas escriben y no "
            "llega nada a Chatwoot. Revisa el bot ya.",
            "webhook-roto",
        )
        raise
    if getattr(c.whatsapp, "ilegibles", 0):
        c._avisar(
            "⚠️ Un mensaje de WhatsApp no se pudo leer",
            "Llegó un mensaje que el bot no entendió y se saltó. Revisa el registro "
            "del bot y Chatwoot.",
            "mensaje-ilegible",
        )
    from app.adapters.channels.whatsapp import formato_desconocido

    try:
        desconocido = formato_desconocido(json.loads(raw))
    except Exception:  # pragma: no cover - si no es JSON ya falló arriba
        desconocido = False
    if desconocido:
        # Ni mensajes ni acuses: Meta cambió dónde los manda (16/10). Se guarda
        # entero para leerlo y se avisa; no hay error que lo delate.
        log.warning("webhook de Meta sin mensajes ni acuses: formato desconocido")
        guardar_webhook_fallido(c, raw, dict(request.headers))
        c._avisar(
            "⚠️ Meta mandó algo que el bot no reconoce",
            "Llegó un aviso de mensajes sin mensajes ni acuses de entrega: puede que "
            "Meta haya cambiado el formato y se estén perdiendo mensajes. Revisa el "
            "bot (quedó guardado en webhook_fallido.json).",
            "formato-desconocido",
        )
    # Meta aceptó un mensaje y DESPUÉS no lo entregó (16/10): Chatwoot lo
    # muestra como enviado, así que se dice en la conversación y al celular.
    from app.adapters.channels.whatsapp import entregas_fallidas

    try:
        for fallida in entregas_fallidas(json.loads(raw)):
            c.no_llego_segun_meta(fallida["wamid"], fallida["motivo"])
    except Exception:
        log.exception("no se pudo revisar los acuses de entrega fallidos")
    mensajes = [con_el_producto(m, activos) for m in leidos]

    encolados = 0
    for m in mensajes:
        # REGLA 3: deduplicar. En SQL es un INSERT ... ON CONFLICT DO NOTHING,
        # que es atómico: si el mismo webhook llega dos veces a la vez, solo
        # uno gana.
        if not c.idempotency.mark_processed("whatsapp", m.external_message_id):
            log.info("duplicado ignorado: %s", m.external_message_id)
            continue
        # `recibir_mensaje` y no `procesar_mensaje`: entre las dos está el
        # agrupador, que espera unos segundos por si la clienta sigue
        # escribiendo. Cuatro mensajes seguidos son UNA pregunta.
        background.add_task(c.recibir_mensaje, m)
        encolados += 1

    registrar(
        ruta_log,
        cuerpo=raw,
        firma_valida=True,
        es_ejemplo=ejemplo,
        encolados=encolados,
        nota="sin mensajes (acuse de entrega)" if not mensajes else "",
    )

    # REGLA 4: ACK inmediato. Meta reintenta si tardamos.
    return {"status": "ok", "recibidos": len(mensajes), "encolados": encolados}


# ---------------------------------------------------------------------------
# Instagram — mismo esqueleto, mismo dominio, distinto adaptador (Fase 5)
# ---------------------------------------------------------------------------


@app.post("/webhook/instagram")
async def instagram_webhook(
    request: Request,
    x_hub_signature_256: Annotated[str | None, Header()] = None,
) -> dict:
    c = get_container()
    raw = await request.body()
    if not c.whatsapp.verify_signature(raw, x_hub_signature_256 or ""):
        raise HTTPException(status_code=403, detail="firma inválida")
    return {"status": "ok", "pendiente": "Fase 5"}


# ---------------------------------------------------------------------------
# Chatwoot: lo que Lía escribe desde la bandeja sale a la clienta
# ---------------------------------------------------------------------------


def _conversacion_de(datos: dict) -> str:
    """Nuestro id de conversación dentro del aviso de Chatwoot.

    El espejo crea el contacto con `identifier` = nuestro id y la conversación
    con ese mismo `source_id`, así que aquí se lee de vuelta sin depender de
    cómo Chatwoot normalice un teléfono.

    En los avisos de MENSAJE la conversación viene en `conversation`; en los de
    CONVERSACIÓN («resuelta», «reabierta») el aviso ES la conversación.
    """
    conversacion = datos.get("conversation") or datos
    meta = (conversacion.get("meta") or {}).get("sender") or {}
    if meta.get("identifier"):
        return str(meta["identifier"])
    buzon = conversacion.get("contact_inbox") or {}
    return str(buzon.get("source_id") or "")


def _canal_de(conv_id: str):
    canal, _, user_id = conv_id.partition(":")
    return {"wa": Channel.WHATSAPP, "ig": Channel.INSTAGRAM}.get(canal), user_id


async def _fotos_de_chatwoot(c, adjuntos: list[dict]) -> tuple[list[str], int]:
    """Baja de Chatwoot las fotos que mandó Lía y las deja listas para WhatsApp.

    Meta baja las imágenes de una URL pública, y la de Chatwoot no lo es: se
    guardan en el mismo almacén que las fotos del anillo terminado (nombres
    aleatorios, solo imágenes, máximo 5 MB) y se sirven desde el túnel.
    Devuelve las URL públicas y cuántos adjuntos NO se pudieron mandar.
    """
    import httpx

    from app.adapters.almacen_fotos import AlmacenDeFotos, FotoInvalida

    almacen = AlmacenDeFotos(c.settings.fotos_dir)
    raiz = c.settings.url_publica.rstrip("/")
    urls, sin_mandar = [], 0
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as cliente:
        for adjunto in adjuntos:
            if adjunto.get("file_type") != "image" or not adjunto.get("data_url"):
                sin_mandar += 1
                continue
            try:
                r = await cliente.get(adjunto["data_url"])
                r.raise_for_status()
                foto = almacen.guardar(r.content)
            except (httpx.HTTPError, FotoInvalida) as exc:
                log.warning("no se pudo pasar una foto de Chatwoot (%s)", exc)
                sin_mandar += 1
                continue
            urls.append(f"{raiz}/panel/foto/{foto.nombre}")
    return urls, sin_mandar


def _es_del_bot(c, datos: dict, conv_id: str) -> bool:
    """¿Este «mensaje de Lía» es una copia que hizo el propio bot?

    Chatwoot devuelve por webhook TODO lo que se escribe en la bandeja, también
    lo que copió el bot. Si no se reconoce, se le reenvía a la clienta (sale
    repetido) y el bot se calla creyendo que lo escribió una persona. Pasó con
    clientas de verdad el 19/09.

    Tres señales, de la más fiable a la de respaldo:
      1. lo firmó el agente bot «VentaBot» (sender.type = agent_bot);
      2. la marca `origen = ventabot` (hoy Chatwoot la descarta, pero cuesta nada);
      3. el texto es idéntico a algo que el bot copió en esa charla hace poco.
    """
    quien = datos.get("sender") or {}
    if quien.get("type") == "agent_bot" or datos.get("sender_type") == "AgentBot":
        return True
    if ((datos.get("content_attributes") or {}).get("origen")) == "ventabot":
        return True
    crm = getattr(c, "crm", None)
    es_eco = getattr(crm, "es_eco", None)
    return bool(es_eco and es_eco(conv_id, datos.get("content") or ""))


@app.post("/webhook/chatwoot")
async def chatwoot_webhook(request: Request, token: str = "") -> dict:
    """Chatwoot como WhatsApp Business: Lía toma la conversación cuando quiere.

    UN SOLO CRITERIO (09/10): quien está ASIGNADO es quien atiende.
    - Escribe (o manda fotos) → le sale a la clienta, el bot se calla 12 h ahí y
      la conversación queda asignada a quien escribió.
    - Se la **asigna** a una persona → el bot se calla YA, antes de escribir.
    - Se la asigna a **VentaBot**, usa la macro «🤖 Devolver al bot» o la
      etiqueta `hacer-devolver-al-bot` → vuelve a atender el bot.
    - **Resolver** solo cierra: no cambia quién la lleva.

    Sin esto, Chatwoot solo sirve para mirar.
    """
    c = get_container()
    esperado = c.settings.chatwoot_webhook_token
    if not esperado:
        raise HTTPException(status_code=404, detail="no encontrado")
    if not hmac.compare_digest(token, esperado):
        raise HTTPException(status_code=403, detail="token inválido")

    datos = await request.json()
    evento = datos.get("event")
    conv_id = _conversacion_de(datos)
    equivalente, user_id = _canal_de(conv_id)

    if evento == "conversation_typing_on":
        # Solo cuenta si quien escribe es una persona del equipo (no la clienta)
        # y no es una nota privada.
        persona = datos.get("user") or {}
        if persona.get("type") == "user" and not datos.get("is_private") and equivalente:
            la_toma_una_persona(c, conv_id, persona.get("id"))
            log.info("Lía está escribiendo en %s: el bot se calla", conv_id)
            return {"status": "pausado"}
        return {"status": "ignorado", "motivo": "no escribe una persona del equipo"}

    if evento == "conversation_updated":
        # Lía corrigió un dato en la ficha de Chatwoot (la dirección, la guía,
        # la talla): se copia al pedido y al panel. Lleno en uno, lleno en
        # todos (29/09). El eco de nuestra propia ficha no cambia nada.
        cambios_ficha = datos.get("changed_attributes") or []
        if equivalente and any("custom_attributes" in (x or {}) for x in cambios_ficha):
            from app.domain.edicion import EdicionInvalida

            try:
                hechos = c.desde_chatwoot(conv_id, datos.get("custom_attributes") or {})
            except EdicionInvalida as exc:
                if c.crm is not None:
                    c.crm.nota(conv_id, f"⚠️ No se pudo guardar lo de la ficha: {exc}")
                return {"status": "ficha rechazada", "motivo": str(exc)}
            if hechos:
                log.info("ficha editada en Chatwoot (%s): %s", conv_id, "; ".join(hechos))
                return {"status": "ficha copiada", "cambios": hechos}
        # Una etiqueta `hacer-…` es una ORDEN de Lía desde Chatwoot (sirve en la
        # app del celular): abono verificado, anillo listo, despachado…
        from app.domain.seguimiento import ETIQUETAS_DE_ACCION

        ordenes = [e for e in (datos.get("labels") or []) if e in ETIQUETAS_DE_ACCION]
        if ordenes and equivalente:
            hechas = [c.accion_desde_crm(conv_id, e) for e in ordenes]
            log.info("Chatwoot en %s: %s", conv_id, " | ".join(hechas))
            return {"status": "accion", "resultado": hechas}
        # Quién la lleva se decide con la ASIGNACIÓN (09/10), igual en el PC y
        # en el celular:
        #   · a una persona (Lía, Camilo) → la toma ella: el bot se calla;
        #   · a VentaBot → se la devuelven al bot;
        #   · sin asignar → no se deja así: vuelve a VentaBot (el celular lo
        #     mostraba como «None» y nadie sabía quién la tenía).
        cambios = datos.get("changed_attributes") or []
        cambio_asignada = any(
            "assignee_id" in (x or {}) or "assignee_agent_bot_id" in (x or {})
            for x in cambios
        )
        if cambio_asignada and equivalente:
            meta = datos.get("meta") or {}
            tipo = meta.get("assignee_type")
            asignada = (meta.get("assignee") or {}).get("id")
            mundo = c.bot._mundo
            if tipo == "User" and asignada:
                mundo.pausar_por_humano(conv_id)
                log.info(
                    "conversación %s asignada a una persona: el bot se calla", conv_id
                )
                return {"status": "pausado"}
            if tipo == "AgentBot":
                if mundo.la_atiende_una_persona(conv_id):
                    devolver_al_bot(c, conv_id)
                    log.info(
                        "conversación %s asignada a VentaBot: vuelve al bot", conv_id
                    )
                    return {"status": "devuelta al bot"}
                # El eco de cuando el propio bot se la asigna: nada que hacer.
                return {"status": "ignorado", "motivo": "ya la tenía el bot"}
            devolver_al_bot(c, conv_id)
            log.info("conversación %s quedó sin asignar: vuelve a VentaBot", conv_id)
            return {"status": "devuelta al bot"}
        return {"status": "ignorado", "motivo": "no es una asignación"}

    if evento == "conversation_status_changed":
        # Resolver es CERRAR, y nada más (09/10): no cambia quién la lleva. Antes
        # «Resuelta» devolvía la charla al bot, y cerrar y devolver se
        # confundían. Para devolverla: la macro «🤖 Devolver al bot», la etiqueta
        # `hacer-devolver-al-bot` o asignarla a VentaBot.
        # Lo que sí hace: «ya lo atendí» → se va la alerta de «necesita persona».
        if datos.get("status") == "resolved" and equivalente:
            c.bot._mundo.ya_la_atendieron(conv_id)
            log.info("conversación %s resuelta: se quita la alerta", conv_id)
            return {"status": "resuelta", "motivo": "resolver no cambia quién la lleva"}
        return {"status": "ignorado", "motivo": "otro cambio de estado"}

    if evento != "message_created":
        return {"status": "ignorado", "motivo": "otro evento"}
    if datos.get("message_type") != "outgoing" or datos.get("private"):
        return {"status": "ignorado", "motivo": "no es una respuesta pública"}
    if _es_del_bot(c, datos, conv_id):
        return {"status": "ignorado", "motivo": "lo copió el propio bot"}
    if equivalente is None:
        return {"status": "ignorado", "motivo": "sin conversación"}

    texto = (datos.get("content") or "").strip()
    from app.domain import plantilla_de_emergencia as emergencia

    if emergencia.es_el_comando(texto):
        # `#retomar` (16/10): la plantilla de emergencia, que llega aunque
        # hayan pasado las 24 h. Si ella contesta, la atiende el bot. Va la que
        # Meta tenga aprobada (la principal o la de respaldo).
        nombre = c._emergencia_aprobada() or emergencia.NOMBRE
        # Por la puerta de siempre: en Chatwoot queda lo que le llegó a ella,
        # no solo el «#retomar» que escribió Lía (17/10).
        c.enviar_a_la_clienta(
            conv_id,
            OutboundMessage(
                channel=equivalente,
                to=user_id,
                kind="template",
                text=emergencia.PLANTILLAS[nombre],
                template_name=nombre,
                conversation_id=conv_id,
                idempotency_key=f"chatwoot:{datos.get('id') or new_id()}",
            ),
        )
        devolver_al_bot(c, conv_id)
        if c.crm is not None:
            c.crm.nota(
                conv_id,
                "🆘 Se le mandó la plantilla de emergencia. "
                "Si responde, la atiende el bot.",
            )
        log.info("plantilla de emergencia desde Chatwoot en %s", conv_id)
        return {"status": "plantilla de emergencia"}

    if emergencia.es_el_comando_asesora(texto):
        # `#asesora` (19/10): ella pidió una PERSONA y ya pasaron las 24 h. La
        # plantilla dice que ya le escribe alguien de verdad y la charla SIGUE
        # CON LA PERSONA (al revés de #retomar): lo que conteste lo ve Lía.
        nombre = c._asesora_aprobada() or emergencia.NOMBRE_ASESORA
        quien = ((datos.get("conversation") or {}).get("meta") or {}).get("sender") or {}
        lee, parametros = emergencia.la_de_asesora(nombre, quien.get("name"))
        c.enviar_a_la_clienta(
            conv_id,
            OutboundMessage(
                channel=equivalente,
                to=user_id,
                kind="template",
                text=lee,
                template_name=nombre,
                template_params=parametros,
                conversation_id=conv_id,
                idempotency_key=f"chatwoot:{datos.get('id') or new_id()}",
            ),
        )
        # Lo que Lía le escribió libre y esperaba la ventana ya sobra: saldría
        # tarde, después de la plantilla («Buen día Laura…» un día después).
        viejos = c.descartar_lo_que_espera_la_ventana(
            user_id, "reemplazado por la plantilla de asesora"
        )
        persona = datos.get("sender") or {}
        la_toma_una_persona(
            c, conv_id, persona.get("id") if persona.get("type") == "user" else None
        )
        if c.crm is not None:
            c.crm.nota(
                conv_id,
                "🙋 Se le mandó la plantilla de asesora. La conversación sigue "
                "contigo: lo que ella conteste lo ves tú, el bot no le responde."
                + (
                    f" ({viejos} mensaje(s) que esperaban las 24 h ya no saldrán.)"
                    if viejos
                    else ""
                ),
            )
        log.info("plantilla de asesora desde Chatwoot en %s", conv_id)
        return {"status": "plantilla de asesora"}

    urls, sin_mandar = await _fotos_de_chatwoot(c, datos.get("attachments") or [])
    if not texto and not urls:
        motivo = "adjunto que no es foto" if sin_mandar else "sin texto"
        return {"status": "ignorado", "motivo": motivo}

    # Si pasaron más de 24 h, el despachador lo deja en espera y lo dice en
    # una nota «⏳» y al celular (informar_que_no_llego, 16/10).
    clave = f"chatwoot:{datos.get('id') or new_id()}"
    for i, url in enumerate(urls):
        # La primera foto lleva el texto como pie, igual que en WhatsApp.
        c.outbox.enqueue(
            OutboundMessage(
                channel=equivalente,
                to=user_id,
                kind="image",
                media_url=url,
                text=texto[:1000] if i == 0 else "",
                idempotency_key=f"{clave}:foto:{i}",
            )
        )
    if texto and not urls:
        c.outbox.enqueue(
            OutboundMessage(
                channel=equivalente,
                to=user_id,
                kind="text",
                text=texto[:4000],
                idempotency_key=clave,
            )
        )
    # Quien escribió desde Chatwoot se queda con la conversación: el bot se calla
    # y en Chatwoot aparece asignada a ELLA (09/10).
    quien = datos.get("sender") or {}
    la_toma_una_persona(
        c, conv_id, quien.get("id") if quien.get("type") == "user" else None
    )
    c.bot._mundo.anotar_mensaje_de_humano(
        conv_id, texto or f"[{len(urls)} foto(s) enviadas por Lía]"
    )
    log.info("respuesta desde Chatwoot en %s (%s foto(s))", conv_id, len(urls))
    return {"status": "enviado", "fotos": len(urls), "sin_mandar": sin_mandar}


# ---------------------------------------------------------------------------
# Pagos (Fase 3) — aquí solo la estructura; se activa con PAYMENT_BACKEND=bold
# ---------------------------------------------------------------------------


@app.post("/webhook/bold")
async def bold_webhook(
    request: Request,
    x_bold_signature: Annotated[str | None, Header()] = None,
) -> dict:
    """Confirmación de pago.

    SECUENCIA COMPLETA (saltarse cualquier paso es una vulnerabilidad):
      a) verificar la firma
      b) RE-CONSULTAR la API con el transaction_id  <- defensa contra replay
      c) comprobar que el estado es APPROVED
      d) comprobar que el MONTO COINCIDE EXACTAMENTE
      e) comprobar que la `reference` es de un pago tuyo en PENDIENTE
      f) idempotencia por event_id
      g) en UNA transacción: payment + order + order_events + outbox
    """
    from app.domain.services import confirmar_pago

    c = get_container()
    raw = await request.body()

    if not c.gateway.verify_webhook(raw, x_bold_signature or ""):  # (a)
        raise HTTPException(status_code=403, detail="firma inválida")

    evento = c.gateway_parse_event(raw)

    if not c.idempotency.mark_processed("bold", evento["event_id"]):  # (f)
        return {"status": "duplicado"}

    if not evento["aprobado"]:  # (c)
        return {"status": "ignorado", "tipo": evento["tipo"]}

    real = c.gateway.fetch_transaction(evento["transaction_id"])  # (b)
    if real.get("status") != "APPROVED":
        log.warning(
            "el webhook dice aprobado pero la API no: %s", evento["transaction_id"]
        )
        return {"status": "rechazado_por_reconsulta"}

    pago = c.payments.get_by_reference(evento["reference"])  # (e)
    if pago is None:
        log.warning("reference desconocida: %s", evento["reference"])
        return {"status": "reference_desconocida"}

    try:
        pedido = confirmar_pago(  # (d) valida el monto adentro, y (g)
            c.orders,
            c.payments,
            pago,
            monto_recibido_cop=evento["monto_cop"],
            transaction_id=evento["transaction_id"],
        )
    except ValueError as exc:
        log.error("pago no aplicado: %s", exc)
        return {"status": "monto_invalido"}

    c.notificar_pago_confirmado(pedido, pago)
    return {"status": "ok", "pedido": pedido.codigo, "estado": pedido.estado}
