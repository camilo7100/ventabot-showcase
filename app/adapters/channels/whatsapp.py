"""Adaptador de WhatsApp Cloud API.

Dos responsabilidades, ambas de traducción pura:
  ENTRADA: payload de Meta  ->  InboundMessage canónico
  SALIDA:  OutboundMessage  ->  payload de la Cloud API

El dominio nunca ve un payload de Meta. Ese es el punto: el día que agregues
Telegram, escribes otro archivo como este y no tocas nada más.

REGLAS DE META QUE ESTÁN CODIFICADAS AQUÍ
-----------------------------------------
  * Ventana de 24 h: fuera de ella SOLO se pueden enviar plantillas aprobadas.
    Por eso `render()` acepta `ventana_abierta` y degrada a plantilla.
  * Botones: MÁXIMO 3. Con más opciones hay que usar una lista interactiva.
  * Límites de caracteres (verificar en la doc oficial): body 1024, footer 60,
    título de botón 20, título de fila 24, descripción de fila 72.
  * Media entrante: el webhook trae un `media_id`, NO una URL. Hay que hacer
    2 llamadas CON TOKEN, y la URL resultante EXPIRA EN 5 MINUTOS.
  * Imágenes: JPEG/PNG hasta 5 MB. Documentos hasta 100 MB.
  * Anuncios «Click to WhatsApp»: el objeto `referral` (id del anuncio,
    `ctwa_clid`…) viene SOLO en el primer mensaje después del clic. Si no se
    lee ahí, no vuelve (ADR 0028).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime

from app.domain.anuncios import Referido
from app.domain.models import (
    Channel,
    InboundMessage,
    MediaRef,
    OutboundMessage,
    conversation_id,
)
from app.domain.ports import TokenDelCanalCaducado

log = logging.getLogger("ventabot.whatsapp")

GRAPH = "https://graph.facebook.com/v21.0"


#: Qué significa cada rechazo de Meta que de verdad aparece, dicho para quien
#: tiene que arreglarlo. Encontrado en la primera prueba real: el registro solo
#: decía «400 Bad Request» y el motivo (131030) se perdía.
QUE_HACER = {
    131030: "el número no está en la lista de destinatarios de prueba: agrégalo "
    "en Meta → WhatsApp → Configuración de la API, o usa el número real",
    131047: "pasaron más de 24 h desde su último mensaje: solo se puede escribir "
    "con una plantilla aprobada",
    131026: "ese número no tiene WhatsApp o no puede recibir mensajes",
    131051: "tipo de mensaje no admitido",
    131052: "no se pudo bajar la foto o el video que ella mandó",
    131053: "Meta no pudo bajar la foto o el video que se le quiso mandar: la "
    "URL pública no responde (¿el túnel está caído?)",
    132000: "la plantilla no tiene los parámetros que espera",
    132001: "la plantilla no existe o no está aprobada en ese idioma",
    133010: "el número del negocio no está registrado en la Cloud API: "
    "corre  vb registrar",
    368: "Meta bloqueó temporalmente el número por políticas: revisa la calidad en el "
    "Administrador de WhatsApp",
    # Los que Meta avisa DESPUÉS, en el acuse «failed» (16/10).
    131000: "falla interna de Meta: escríbele otra vez en un rato",
    131021: "se intentó escribir al mismo número del negocio",
    131031: "la cuenta de WhatsApp del negocio está bloqueada: revisa el "
    "Administrador de WhatsApp",
    131042: "problema con el pago de la cuenta de WhatsApp: revisa el método de pago "
    "en Meta",
    131048: "Meta frenó los envíos por reportes de spam: revisa la calidad del número",
    131049: "Meta no lo entregó para no saturarla (límite de mensajes de marketing por "
    "persona): inténtalo en unos días",
    131050: "ella pidió no recibir mensajes de marketing de este número",
    131056: "demasiados mensajes seguidos a la misma clienta: espera un poco",
    130472: "Meta la puso en un experimento y no le entrega mensajes de marketing",
    132015: "la plantilla está pausada por baja calidad",
    132016: "la plantilla está desactivada por baja calidad",
}


def motivo_de_meta(codigo: int | None, mensaje: str = "") -> str:
    """El porqué de un rechazo dicho en cristiano, o lo que dijo Meta."""
    return QUE_HACER.get(codigo or 0) or (
        f"Meta dijo: {mensaje} (#{codigo})" if mensaje else f"error de Meta #{codigo}"
    )


def entregas_fallidas(payload: dict) -> list[dict]:
    """Los acuses «failed»: Meta aceptó el mensaje y DESPUÉS no lo entregó (16/10).

    Chatwoot ya lo mostró como enviado; esto es lo que permite decir la verdad.
    Cada uno: el `wamid` del mensaje, el código de Meta y su explicación.
    """
    fallidas = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for estado in (change.get("value") or {}).get("statuses") or []:
                if estado.get("status") != "failed":
                    continue
                error = (estado.get("errors") or [{}])[0]
                codigo = error.get("code")
                detalle = (
                    (error.get("error_data") or {}).get("details")
                    or error.get("message")
                    or error.get("title")
                    or ""
                )
                fallidas.append(
                    {
                        "wamid": estado.get("id"),
                        "codigo": codigo,
                        "motivo": motivo_de_meta(codigo, detalle),
                    }
                )
    return fallidas


class RechazoDeMeta(RuntimeError):
    """Meta dijo que no, y aquí va POR QUÉ y qué hacer.

    Se guarda así en la outbox y sale así en los avisos al celular: un código y
    una frase que se pueda leer sin abrir la documentación de Meta.
    """

    def __init__(self, codigo: int | None, mensaje: str) -> None:
        self.codigo = codigo
        consejo = QUE_HACER.get(codigo or 0, "")
        texto = f"Meta rechazó el mensaje (#{codigo}): {mensaje}"
        super().__init__(f"{texto} → {consejo}" if consejo else texto)


def _rechazo(respuesta) -> RechazoDeMeta:
    try:
        error = respuesta.json().get("error", {})
    except Exception:
        error = {}
    detalle = (error.get("error_data") or {}).get("details") or error.get("message")
    return RechazoDeMeta(
        error.get("code"), (detalle or f"HTTP {respuesta.status_code}")[:300]
    )


def _codigo_de_error(respuesta) -> int | None:
    """El `error.code` que manda Graph, o None si la respuesta no lo trae."""
    try:
        return respuesta.json().get("error", {}).get("code")
    except Exception:
        return None


MAX_BOTONES = 3
MAX_FILAS_LISTA = 10
MAX_TITULO_BOTON = 20
MAX_TITULO_FILA = 24
MAX_DESC_FILA = 72
MAX_BODY = 1024


class WhatsAppAdapter:
    def __init__(
        self,
        phone_number_id: str,
        access_token: str,
        app_secret: str,
        verify_token: str,
    ) -> None:
        self.phone_number_id = phone_number_id
        self._token = access_token
        self._app_secret = app_secret.encode()
        self.verify_token = verify_token

    # -- seguridad ----------------------------------------------------------

    def verify_signature(self, raw_body: bytes, signature: str) -> bool:
        """`X-Hub-Signature-256: sha256=<hex>` sobre el BODY CRUDO."""
        esperado = (
            "sha256=" + hmac.new(self._app_secret, raw_body, hashlib.sha256).hexdigest()
        )
        return hmac.compare_digest(esperado, signature or "")

    def verify_challenge(self, mode: str, token: str, challenge: str) -> str | None:
        """Handshake GET que Meta hace al registrar el webhook."""
        if mode == "subscribe" and token == self.verify_token:
            return challenge
        return None

    # -- entrada ------------------------------------------------------------

    def parse_webhook(self, payload: dict) -> list[InboundMessage]:
        """Payload de Meta -> lista de InboundMessage.

        Un solo webhook puede traer varios mensajes, y también traer SOLO
        estados de entrega (sin mensajes). Hay que soportar ambos.
        """
        out: list[InboundMessage] = []
        #: Cuántos mensajes de ESTE webhook no se pudieron leer (la API avisa).
        self.ilegibles = 0
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                # 14/10: Meta empezó a mandar contactos SIN `wa_id` (con `user_id`,
                # el identificador nuevo de usuario). `c["wa_id"]` tumbaba el
                # webhook entero y ningún mensaje entraba (KeyError 'wa_id').
                contactos: dict[str, str | None] = {}
                for c in value.get("contacts", []):
                    nombre = (c.get("profile") or {}).get("name")
                    for clave in (c.get("wa_id"), c.get("user_id")):
                        if clave:
                            contactos[clave] = nombre
                for msg in value.get("messages", []):
                    if msg.get("type") == "reaction" and not (
                        (msg.get("reaction") or {}).get("emoji")
                    ):
                        # Quitó una reacción: no hay nada que contestar ni ver.
                        continue
                    try:
                        entrante = self._to_inbound(msg, contactos)
                    except Exception:
                        # Un mensaje raro no puede tumbar a los demás del lote.
                        log.exception("mensaje de WhatsApp que no se pudo leer")
                        self.ilegibles += 1
                        continue
                    if entrante is not None:
                        out.append(entrante)
        return out

    def _to_inbound(self, msg: dict, contactos: dict) -> InboundMessage | None:
        # El número; si Meta solo trae el identificador nuevo, ese (sin número
        # no se le puede contestar por número, pero el mensaje no se pierde).
        wa_id = msg.get("from") or msg.get("from_user_id")
        if not wa_id:
            log.warning("mensaje de WhatsApp sin remitente: %s", sorted(msg))
            self.ilegibles = getattr(self, "ilegibles", 0) + 1
            return None
        tipo = msg.get("type")

        texto: str | None = None
        media: list[MediaRef] = []

        if tipo == "text":
            texto = msg["text"]["body"]
        elif tipo == "interactive":
            inter = msg["interactive"]
            if inter.get("type") == "button_reply":
                texto = inter["button_reply"]["id"]
            elif inter.get("type") == "list_reply":
                texto = inter["list_reply"]["id"]
        elif tipo in {"image", "document", "audio", "video", "sticker"}:
            cuerpo = msg[tipo]
            texto = cuerpo.get("caption")
            media.append(
                MediaRef(
                    kind=tipo,  # type: ignore[arg-type]
                    media_id=cuerpo.get("id"),
                    mime_type=cuerpo.get("mime_type"),
                    sha256=cuerpo.get("sha256"),
                    filename=cuerpo.get("filename"),
                )
            )
        elif tipo == "button":
            # Tocó un botón de respuesta rápida de una PLANTILLA: es lo que dijo.
            texto = (msg.get("button") or {}).get("text")
        elif tipo in {"unsupported", "reaction", "location", "contacts"}:
            # No traen archivo, pero son algo que ella mandó (27/09: salían
            # como «[adjunto]» y había que adivinar qué era).
            media.append(MediaRef(kind=tipo, detalle=detalle_sin_archivo(tipo, msg)))  # type: ignore[arg-type]

        return InboundMessage(
            channel=Channel.WHATSAPP,
            external_message_id=msg["id"],
            conversation_id=conversation_id(Channel.WHATSAPP, wa_id),
            sender_id=wa_id,
            sender_name=contactos.get(wa_id) or contactos.get(msg.get("from_user_id")),
            text=texto,
            media=media,
            timestamp=datetime.fromtimestamp(int(msg["timestamp"]), tz=UTC),
            raw=msg,
            referido=referido_de(msg),
        )

    # -- salida -------------------------------------------------------------

    def render(self, m: OutboundMessage, *, ventana_abierta: bool = True) -> dict:
        """OutboundMessage abstracto -> payload concreto de la Cloud API.

        Aquí es donde se decide botones vs lista, y texto libre vs plantilla.
        El dominio nunca toma esta decisión.
        """
        base = {"messaging_product": "whatsapp", **destino(m.to)}

        # Fuera de la ventana de 24 h, Meta SOLO acepta plantillas aprobadas.
        if not ventana_abierta or m.kind == "template":
            if not m.template_name:
                raise ValueError(
                    "Ventana de 24 h cerrada y no se especificó plantilla. "
                    "Este chequeo va en el outbox_dispatcher, antes de enviar."
                )
            return {
                **base,
                "type": "template",
                "template": {
                    "name": m.template_name,
                    "language": {"code": "es"},
                    "components": _componentes_plantilla(m.template_params),
                },
            }

        if m.kind == "cta_url" and m.cta_url:
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "cta_url",
                    "body": {"text": m.text[:MAX_BODY]},
                    "action": {
                        "name": "cta_url",
                        "parameters": {
                            "display_text": (m.cta_label or "Pagar")[:MAX_TITULO_BOTON],
                            "url": m.cta_url,
                        },
                    },
                },
            }

        if m.kind == "options" and m.options:
            if len(m.options) <= MAX_BOTONES:
                # Con foto arriba (los recordatorios por días, 13/10): la cabecera
                # de los botones puede ser una imagen.
                cabecera = (
                    {"header": {"type": "image", "image": {"link": m.media_url}}}
                    if m.media_url
                    else {}
                )
                return {
                    **base,
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        **cabecera,
                        "body": {"text": m.text[:MAX_BODY]},
                        "action": {
                            "buttons": [
                                {
                                    "type": "reply",
                                    "reply": {
                                        "id": o.id,
                                        "title": o.title[:MAX_TITULO_BOTON],
                                    },
                                }
                                for o in m.options
                            ]
                        },
                    },
                }
            return {
                **base,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": m.text[:MAX_BODY]},
                    "action": {
                        "button": "Ver opciones",
                        "sections": [
                            {
                                "title": "Productos",
                                "rows": [
                                    {
                                        "id": o.id,
                                        "title": o.title[:MAX_TITULO_FILA],
                                        "description": (o.description or "")[
                                            :MAX_DESC_FILA
                                        ],
                                    }
                                    for o in m.options[:MAX_FILAS_LISTA]
                                ],
                            }
                        ],
                    },
                },
            }

        if m.kind in ("image", "video") and m.media_url:
            # Mismo formato para los dos, solo cambia la clave. Meta baja el
            # archivo de la URL con un GET anónimo, así que tiene que ser
            # pública — por eso el túnel hace falta también para esto.
            return {
                **base,
                "type": m.kind,
                m.kind: {"link": m.media_url, "caption": m.text[:MAX_BODY]},
            }

        return {**base, "type": "text", "text": {"body": m.text[:MAX_BODY]}}

    def send(self, m: OutboundMessage, *, ventana_abierta: bool = True) -> str:
        import httpx

        r = httpx.post(
            f"{GRAPH}/{self.phone_number_id}/messages",
            headers={"Authorization": f"Bearer {self._token}"},
            json=self.render(m, ventana_abierta=ventana_abierta),
            timeout=15,
        )
        # Un 401 NO es un fallo transitorio: el token caducó y reintentar
        # cinco veces con espera creciente solo llena el log de ruido idéntico
        # durante diez minutos. Se distingue aquí para que el despachador
        # pueda decir QUÉ hacer en vez de repetir el error de httpx.
        if r.status_code == 401 or _codigo_de_error(r) == 190:
            raise TokenDelCanalCaducado(
                "el token de acceso de Meta caducó o fue revocado (401)"
            )
        if not r.is_success:
            raise _rechazo(r)
        return r.json()["messages"][0]["id"]

    # -- media --------------------------------------------------------------

    def download_media(self, media_id: str) -> bytes:
        """DOS pasos, AMBOS con token. La URL del paso 1 expira en 5 MINUTOS.

        Descarga y persiste en tu propio storage inmediatamente. Si guardas la
        URL y la usas 10 minutos después, falla.
        """
        import httpx

        h = {"Authorization": f"Bearer {self._token}"}
        meta = httpx.get(
            f"{GRAPH}/{media_id}",
            params={"phone_number_id": self.phone_number_id},
            headers=h,
            timeout=15,
        )
        meta.raise_for_status()
        url = meta.json()["url"]
        # Sin el header Authorization en ESTA segunda llamada, falla.
        binario = httpx.get(url, headers=h, timeout=30)
        binario.raise_for_status()
        return binario.content

    def estados_de_plantillas(self, waba_id: str) -> dict[str, str]:
        """El estado de TODAS las plantillas, en una sola vuelta (el banco de
        plantillas tiene cientos: preguntar nombre por nombre no se puede)."""
        import httpx

        estados: dict[str, str] = {}
        url, params = (
            f"{GRAPH}/{waba_id}/message_templates",
            {
                "fields": "name,status",
                "limit": 200,
            },
        )
        while url:
            r = httpx.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=20,
            )
            r.raise_for_status()
            cuerpo = r.json()
            for p in cuerpo.get("data", []):
                estados[p["name"]] = p.get("status", "")
            url, params = (cuerpo.get("paging") or {}).get("next"), None
        return estados

    def borrar_plantilla(self, waba_id: str, nombre: str) -> None:
        """Borra una plantilla (todos sus idiomas). Solo la usa
        `scripts/banco_de_plantillas.py limpiar --borrar`."""
        import httpx

        r = httpx.delete(
            f"{GRAPH}/{waba_id}/message_templates",
            params={"name": nombre},
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=20,
        )
        r.raise_for_status()

    def estado_de_plantilla(self, waba_id: str, nombre: str) -> str | None:
        """APPROVED, PENDING, REJECTED… de una plantilla; None si no existe."""
        import httpx

        r = httpx.get(
            f"{GRAPH}/{waba_id}/message_templates",
            params={"name": nombre, "fields": "name,status"},
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=15,
        )
        r.raise_for_status()
        for p in r.json().get("data", []):
            if p.get("name") == nombre:
                return p.get("status")
        return None


def formato_desconocido(payload: dict) -> bool:
    """¿Un aviso de mensajes de Meta que no trae ni mensajes ni acuses? (16/10)

    Si Meta mueve los mensajes a otra parte del paquete, `parse_webhook` no
    falla: no encuentra nada y parece un acuse más. Sería el 14/10 otra vez,
    pero callado. Esto lo delata para guardarlo y avisar.
    """
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field", "messages") != "messages":
                continue  # otros avisos (plantillas, cuenta…): no son de clientas
            value = change.get("value") or {}
            if not any(value.get(k) for k in ("messages", "statuses", "errors")):
                return True
    return False


def destino(to: str) -> dict:
    """A quién va: por número (`to`) o por el identificador nuevo (`recipient`).

    Quien entró sin teléfono (solo con su identificador nuevo, 14/10) se le
    contesta con `recipient`: Meta no acepta ese identificador en `to`.
    """
    if to.isdigit():
        return {"to": to}
    return {"recipient_type": "individual", "recipient": to}


def referido_de(msg: dict) -> Referido | None:
    """El anuncio «Click to WhatsApp» del que vino este mensaje, o None.

    Meta lo manda en `messages[].referral` SOLO en el primer mensaje que ella
    escribe después de tocar el anuncio (ADR 0028). Sin `source_id` no hay
    con qué cruzarlo con el costo del anuncio, así que no cuenta.
    """
    r = msg.get("referral")
    if not isinstance(r, dict):
        return None
    anuncio_id = str(r.get("source_id") or "").strip()
    if not anuncio_id:
        return None

    def campo(nombre: str, tope: int = 300) -> str:
        return str(r.get(nombre) or "").strip()[:tope]

    try:
        cuando = datetime.fromtimestamp(int(msg["timestamp"]), tz=UTC)
    except (KeyError, TypeError, ValueError):
        cuando = datetime.now(UTC)
    return Referido(
        anuncio_id=anuncio_id[:100],
        tipo=campo("source_type", 20),
        url=campo("source_url", 500),
        titulo=campo("headline"),
        texto=campo("body", 1000),
        medio=campo("media_type", 20),
        ctwa_clid=campo("ctwa_clid", 500),
        cuando=cuando,
    )


def detalle_sin_archivo(tipo: str, msg: dict) -> str:
    """Lo legible de un mensaje sin archivo: el emoji, la dirección, el contacto."""
    if tipo == "reaction":
        return (msg.get("reaction") or {}).get("emoji") or ""
    if tipo == "location":
        lugar = msg.get("location") or {}
        partes = [lugar.get("name") or "", lugar.get("address") or ""]
        if lugar.get("latitude") is not None and lugar.get("longitude") is not None:
            partes.append(
                f"https://maps.google.com/?q={lugar['latitude']},{lugar['longitude']}"
            )
        return " · ".join(p for p in partes if p)
    if tipo == "contacts":
        vistos = []
        for c in msg.get("contacts") or []:
            nombre = (c.get("name") or {}).get("formatted_name") or ""
            telefonos = ", ".join(t.get("phone", "") for t in c.get("phones") or [])
            vistos.append(" ".join(x for x in (nombre, telefonos) if x))
        return " · ".join(v for v in vistos if v)
    if tipo == "unsupported":
        # Lo único que dice Meta, y casi siempre es «unknown»: eso no aporta.
        cual = (msg.get("unsupported") or {}).get("type") or ""
        return "" if cual == "unknown" else cual
    return ""


def _componentes_plantilla(params: dict) -> list[dict]:
    """Los valores de {{1}}, {{2}}… EN ORDEN NUMÉRICO.

    Meta no recibe nombres: recibe una lista posicional. Si el orden se
    invierte, la clienta ve el código del pedido donde iba el monto y nadie se
    entera hasta que ella pregunta qué significa "PED-2026-0417 pesos".

    Antes esto dependía del orden de inserción del `dict`. Funcionaba, pero
    apoyarse en eso es apostar a que nadie construya el diccionario de otra
    forma. Ordenar por la clave numérica lo hace explícito.
    """
    if not params:
        return []
    params = dict(params)
    # La foto de la cabecera (plantillas con IMAGEN, 13/10): va aparte del cuerpo.
    imagen = params.pop("imagen", None)
    componentes = (
        [{"type": "header", "parameters": [{"type": "image", "image": {"link": imagen}}]}]
        if imagen
        else []
    )
    en_orden = sorted(params.items(), key=lambda kv: int(kv[0]))
    if en_orden:
        componentes.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": str(v)} for _, v in en_orden],
            }
        )
    return componentes
