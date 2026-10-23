"""Chatwoot: que Lía vea TODAS las conversaciones en un solo sitio.

════════════════════════════════════════════════════════════════════════════
POR QUÉ UN ESPEJO Y NO UN CAMBIO DE CANAL
════════════════════════════════════════════════════════════════════════════
Chatwoot puede conectarse él mismo a WhatsApp y quedarse con el canal, y el
bot pasar a ser un webhook suyo. Es la arquitectura bonita y es la que se
recomienda en su documentación.

Aquí NO se hace eso, y es deliberado: el canal funciona, está probado, y
cambiarlo significa volver a pelear con Meta —firmas, plantillas, ventana de
24 horas— a cambio de nada que la clienta note. Lo que hace falta hoy es que
Lía pueda mirar, y para eso basta con un espejo.

El bot sigue siendo el dueño del canal y va copiando cada mensaje a Chatwoot,
en los dos sentidos, con las etiquetas de lo que hay que revisar. Lía abre
Chatwoot y ve la conversación entera, quién es, qué pidió y qué falta.

El día que convenga invertirlo —Chatwoot dueño del canal, el bot detrás— este
adaptador se tira y se escribe el otro. Nada más del sistema se entera.

════════════════════════════════════════════════════════════════════════════
NUNCA BLOQUEA, NUNCA ROMPE
════════════════════════════════════════════════════════════════════════════
La clienta nunca espera por Chatwoot: copiar va en un hilo aparte, con un
tope de tiempo corto por llamada. Si Chatwoot está caído, el turno sigue igual.

════════════════════════════════════════════════════════════════════════════
PERO TODO LLEGA, AUNQUE SEA HORAS DESPUÉS
════════════════════════════════════════════════════════════════════════════
Chatwoot es la ÚNICA forma en que Camilo y Lía ven la charla y contestan
(07/10). Las copias van a una cola en la base de datos (`cola.py`), no en la
memoria: si Chatwoot se cae por horas, si el bot se reinicia, si quien encoló
fue un script que ya terminó, cada copia espera ahí, en orden, y se reintenta
sin límite hasta que Chatwoot la recibe. La que llega tarde dice a qué hora
pasó de verdad.

Lo único que no se reintenta para siempre es lo que Chatwoot RECHAZA por sí
mismo (un archivo que no acepta, un dato inválido): eso taparía todo lo que
viene detrás. Se aparta, queda guardado y se avisa.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import threading
import time
from collections import deque
from datetime import UTC, datetime, timedelta, timezone

from app.adapters.crm.cola import ColaEnMemoria

log = logging.getLogger("ventabot.chatwoot")

#: Cuánto se espera a Chatwoot. Corto a propósito: esto corre en segundo
#: plano, pero un hilo bloqueado media hora es un hilo perdido.
ESPERA_S = 8

#: Solo para la cola EN MEMORIA (pruebas, un proceso sin base de datos): que
#: un Chatwoot caído no se coma la memoria. La de la base de datos no tiene tope.
COLA_MAXIMA = 500
#: Al cerrar el proceso (un script, un reinicio del servidor), cuánto se espera
#: a que la cola termine de copiar a Chatwoot antes de salir. Con la cola en la
#: base no se pierde nada si no alcanza: la retoma el servidor.
TOPE_AL_SALIR_S = 20.0
#: Si Chatwoot está caído al cerrar, se espera solo esto (por si vuelve ya).
ESPERA_SI_CAIDO_S = 3.0
#: Pausas entre reintentos mientras Chatwoot no responde. La última se repite
#: sin fin: un minuto entre intentos, el tiempo que haga falta.
REINTENTOS_S = (2.0, 5.0, 15.0, 30.0, 60.0)
#: Cada cuánto se mira la cola cuando no hay nada (otro proceso pudo encolar).
MIRAR_S = 5.0
#: Si Chatwoot lleva este rato sin recibir copias, se avisa (una vez por caída).
AVISAR_TRAS = timedelta(minutes=15)
#: Lo que Chatwoot RECHAZA por sí mismo (no por estar caído). Tras unos intentos
#: se aparta, para que no tape la fila.
RECHAZOS_HTTP = frozenset({400, 413, 415, 422})
INTENTOS_SI_LA_RECHAZA = 3
#: Un error que no es de red ni de Chatwoot (algo raro en la copia misma).
INTENTOS_SI_ES_RARO = 10
#: Una copia que llega con más de este retraso dice a qué hora pasó de verdad.
TARDE = timedelta(minutes=10)

_COLOMBIA = timezone(timedelta(hours=-5), "America/Bogota")

#: Cuánto tiempo se recuerda lo que el bot copió, para reconocer su eco. Chatwoot
#: devuelve cada copia por webhook en segundos; cinco minutos es de sobra.
ECO_S = 300

#: Etiqueta que pone el turno cuando la clienta necesita a una persona.
NECESITA_PERSONA = "necesita-persona"


def _de_quien(tarea) -> str:
    """Toda tarea es `[tipo, conversation_id, ...]`."""
    return tarea[1]


def _codigo_http(exc: Exception) -> int | None:
    return getattr(getattr(exc, "response", None), "status_code", None)


def _cuantas_veces(exc: Exception) -> int | None:
    """Cuántos intentos merece antes de apartarla. None = sin límite."""
    import httpx

    codigo = _codigo_http(exc)
    if codigo is not None:
        return INTENTOS_SI_LA_RECHAZA if codigo in RECHAZOS_HTTP else None
    if isinstance(exc, httpx.HTTPError | OSError):
        return None  # Chatwoot caído, la red, un timeout: esperar lo que haga falta
    return INTENTOS_SI_ES_RARO


def _sin_ruido():
    """Para anotar en la cola desde el hilo: si la base está ocupada un
    instante, la copia sigue ahí y se reintenta en la siguiente vuelta."""
    return contextlib.suppress(Exception)


def _cuando_paso(creada: datetime) -> str:
    """«🕓 07/10 2:32 p. m.»: la hora de verdad de una copia que llegó tarde."""
    local = creada.astimezone(_COLOMBIA)
    hora = local.hour % 12 or 12
    mitad = "a. m." if local.hour < 12 else "p. m."
    return f"🕓 {local:%d/%m} {hora}:{local:%M} {mitad}"


#: Las que `mimetypes` no sabe (o sabe mal) en todos los sistemas. Chatwoot
#: decide si muestra un reproductor o un clip por la EXTENSIÓN: un audio de
#: iPhone llamado «adjunto.bin» salía como archivo raro y no se podía oír.
_EXTENSIONES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/amr": "amr",
    "video/mp4": "mp4",
    "video/3gpp": "3gp",
    "application/pdf": "pdf",
}


def _nombre_de_archivo(adjunto: dict, mime: str, i: int) -> str:
    """El nombre con que se sube: el suyo si lo trae (un PDF), si no uno con la
    extensión correcta para que Chatwoot lo muestre como foto, audio o video."""
    import mimetypes
    import re

    propio = re.sub(r"[\\/\r\n\"]", "_", (adjunto.get("filename") or "").strip())[:120]
    if propio:
        return propio
    extension = _EXTENSIONES.get(mime) or (
        (mimetypes.guess_extension(mime) or ".bin").lstrip(".") if mime else "bin"
    )
    return f"adjunto-{i}.{extension}"


def _no_existe(exc: Exception) -> bool:
    """¿Es un «eso ya no existe» de Chatwoot, y no un fallo pasajero?"""
    respuesta = getattr(exc, "response", None)
    return getattr(respuesta, "status_code", None) == 404


class ChatwootCRM:
    """Espejo de las conversaciones. Implementa `app.domain.ports.CrmPort`."""

    def __init__(
        self,
        base_url: str,
        token: str,
        account_id: int,
        inbox_id: int,
        espera_s: int = ESPERA_S,
        descargar=None,
        bot_token: str = "",
        cola=None,
        avisar=None,
    ) -> None:
        self._base = base_url.rstrip("/")
        #: Con qué se firman los mensajes del bot (agente bot «VentaBot»). Sin
        #: él salen a nombre de la persona dueña de `token`, y en Chatwoot no
        #: se distingue quién escribió qué.
        self._token_bot = bot_token or token
        #: conversación -> [(cuándo, texto)] de lo último que copió el bot. Se
        #: anota AL ENCOLAR, antes de que Chatwoot lo reciba: el webhook del eco
        #: nunca puede ganarle la carrera.
        self._copiado: dict[str, deque] = {}
        self._candado = threading.Lock()
        #: El nombre que ya se le puso al contacto, para no reescribirlo.
        self._nombres: dict[str, str] = {}
        #: Cómo se bajan de Meta las fotos y audios que manda la clienta. Se
        #: bajan EN EL HILO, nunca en el turno: la clienta no espera por esto.
        self._descargar = descargar
        self._token = token
        self._cuenta = account_id
        self._inbox = inbox_id
        self._espera = espera_s
        #: conversation_id de VentaBot -> (contacto, conversación) de Chatwoot.
        #: En memoria: si el proceso se reinicia se vuelven a buscar, que
        #: cuesta una llamada y no pierde nada.
        self._cache: dict[str, tuple[int, int]] = {}
        #: Lo que falta copiar. En el bot de verdad, la de la base de datos
        #: (`ColaEnSqlite`): sobrevive caídas y reinicios. Sin ella, en memoria.
        self._cola = cola if cola is not None else ColaEnMemoria(COLA_MAXIMA)
        self._duradera = cola is not None
        #: Cómo se le avisa a Camilo (ntfy) que Chatwoot no está recibiendo.
        self._avisar = avisar
        self._avisado_lleno = False
        #: Hay algo nuevo en la cola: el hilo no espera a su siguiente vuelta.
        self._hay = threading.Event()
        #: Para despertar al hilo de una pausa cuando el proceso se cierra.
        self._parar = threading.Event()
        #: Desde cuándo Chatwoot no recibe (None = está recibiendo).
        self._falla_desde: float | None = None
        #: El id del agente bot VentaBot en Chatwoot (se pregunta la primera vez).
        self._bot: int | None = None
        self._avisado_caido = False
        #: `cerrar()` lo pone en True y el hilo deja de hablar con nadie.
        self._cerrado = False
        self._hilo = threading.Thread(target=self._trabajar, name="chatwoot", daemon=True)
        self._hilo.start()
        # Pasó el 07/10: se le mandó a una clienta la información de la cadena
        # desde un script, el script terminó y en Chatwoot no quedó nada. Al
        # salir, se espera un rato a que la cola termine; lo que no alcance
        # queda en la base y lo copia el servidor.
        atexit.register(self._al_salir)

    def _poner(self, tarea) -> None:
        """A la cola, sin hacer esperar a nadie. Nunca lanza."""
        try:
            self._cola.poner(tarea)
        except Exception as exc:
            if not self._avisado_lleno:
                log.error(
                    "no se pudo guardar una copia para Chatwoot (%s): el bot sigue "
                    "igual, pero esa copia no va a aparecer",
                    exc,
                )
                self._avisado_lleno = True
            return
        self._avisado_lleno = False
        self._hay.set()

    # -- puerto -------------------------------------------------------------

    def registrar(
        self,
        conversation_id: str,
        texto: str,
        *,
        entrante: bool,
        nombre: str = "",
        etiquetas: tuple[str, ...] = (),
        atributos: dict | None = None,
        adjuntos: tuple[dict, ...] = (),
    ) -> None:
        """Encola una copia. Devuelve INMEDIATAMENTE, siempre.

        `adjuntos` son las REFERENCIAS de lo que mandó la clienta (fotos, notas
        de voz, PDF), no los bytes: se bajan en el hilo, para que un archivo
        pesado no le cueste un segundo a la respuesta.
        """
        if not texto and not etiquetas and not adjuntos:
            return
        if not entrante and texto:
            self._recordar(conversation_id, texto)
        self._poner(
            [
                "copia",
                conversation_id,
                texto,
                entrante,
                nombre,
                list(etiquetas),
                atributos or {},
                [dict(a) for a in adjuntos],
            ]
        )

    def marcar_estado(self, conversation_id: str, estado: str) -> None:
        """Encola el cambio de estado. Devuelve INMEDIATAMENTE, siempre."""
        self._poner(["estado", conversation_id, estado])

    def es_eco(self, conversation_id: str, texto: str) -> bool:
        """¿Lo copió el bot hace poco? Si sí, se «gasta»: cada copia, un eco."""
        limpio = (texto or "").strip()
        if not limpio:
            return False
        ahora = time.monotonic()
        with self._candado:
            recientes = self._copiado.get(conversation_id)
            if not recientes:
                return False
            for i, (cuando, copiado) in enumerate(recientes):
                if ahora - cuando <= ECO_S and copiado == limpio:
                    del recientes[i]
                    return True
        return False

    def _recordar(self, conversation_id: str, texto: str, si_falta: bool = False) -> None:
        """`si_falta`: solo si no está ya (al copiar, para no dejar dos marcas de
        la misma copia: la segunda se tragaría un mensaje igual de Lía)."""
        ahora = time.monotonic()
        limpio = texto.strip()
        with self._candado:
            recientes = self._copiado.setdefault(conversation_id, deque(maxlen=50))
            while recientes and ahora - recientes[0][0] > ECO_S:
                recientes.popleft()
            if si_falta and any(copiado == limpio for _, copiado in recientes):
                return
            recientes.append((ahora, limpio))

    # -- el hilo ------------------------------------------------------------

    def pendientes(self) -> int:
        """Cuántas copias faltan por llegar a Chatwoot."""
        try:
            return self._cola.pendientes()
        except Exception:  # pragma: no cover - la base ocupada
            return 0

    def vaciar(self, tope_s: float = TOPE_AL_SALIR_S) -> bool:
        """Espera a que la cola termine de copiar, sin tirar nada. True si quedó
        todo en Chatwoot; False si se pasó el tope (y se avisa cuántas faltan).

        Con la cola en la base, si Chatwoot está caído se espera poco: lo que
        falta ya está guardado y lo copia el servidor cuando vuelva."""
        arranque = time.monotonic()
        while self.pendientes() and not self._cerrado:
            caido = self._falla_desde is not None
            tope = min(tope_s, ESPERA_SI_CAIDO_S) if caido else tope_s
            if time.monotonic() - arranque > tope:
                log.warning(
                    "quedan %s copias por pasar a Chatwoot%s",
                    self.pendientes(),
                    ": están guardadas y llegarán solas" if self._duradera else "",
                )
                return False
            time.sleep(0.05)
        return True

    def _al_salir(self) -> None:
        if not self._cerrado:
            self.vaciar()
            self._cerrado = True
            self._parar.set()
            self._cola.soltar()

    def cerrar(self) -> None:
        """Deja de intentar copiar.

        Se usa en las pruebas y al cerrar: un hilo que sigue llamando a un
        Chatwoot que ya no importa llena el registro de avisos minutos después,
        cuando nadie sabe de dónde salen. Con la cola en la base no se tira
        nada (la retoma el siguiente proceso); la de memoria se vacía.
        """
        self._cerrado = True
        self._parar.set()
        self._hay.set()
        with _sin_ruido():  # cerrar nunca falla
            self._cola.soltar()
            if not self._duradera:
                self._cola.vaciar_todo()

    def _trabajar(self) -> None:  # pragma: no cover - hilo de fondo
        vuelta = 0
        while not self._cerrado:
            self._hay.clear()
            try:
                pendiente = self._cola.tomar()
            except Exception as exc:
                log.warning("no se pudo leer la cola de Chatwoot (%s)", exc)
                self._parar.wait(MIRAR_S)
                continue
            if pendiente is None:
                self._hay.wait(MIRAR_S)
                continue
            try:
                self._hacer_una(pendiente.tarea, pendiente.creada)
            except Exception as exc:
                if self._cerrado:
                    with _sin_ruido():
                        self._cola.fallo(pendiente.id, str(exc))
                    return
                self._no_llego(pendiente, exc)
                pausa = REINTENTOS_S[min(vuelta, len(REINTENTOS_S) - 1)]
                vuelta += 1
                self._parar.wait(pausa)
                continue
            with _sin_ruido():
                self._cola.hecha(pendiente.id)
            vuelta = 0
            self._volvio()

    def _hacer_una(self, tarea, creada: datetime) -> None:
        try:
            self._hacer(tarea, creada)
        except Exception as exc:
            # Un 404 dice «eso que recuerdas ya no existe»: la conversación se
            # borró en Chatwoot y la memoria apunta a un id muerto. Se olvida y
            # se rehace. Sin esto, cada mensaje de esa persona se perdía para
            # siempre —hasta reiniciar el bot— y en Chatwoot no aparecía nada
            # (20/09).
            if not _no_existe(exc):
                raise
            self._olvidar(_de_quien(tarea))
            log.info("la conversación de Chatwoot ya no estaba: se rehace")
            self._hacer(tarea, creada)

    def _no_llego(self, pendiente, exc: Exception) -> None:
        """Vuelve a la fila (se reintenta sin fin), salvo que Chatwoot la
        RECHACE por sí misma: esa se aparta para no tapar a las demás."""
        error = f"{type(exc).__name__}: {exc}"[:500]
        tope = _cuantas_veces(exc)
        if tope is not None and pendiente.intentos + 1 >= tope:
            with _sin_ruido():
                self._cola.apartar(pendiente.id, error)
            log.error("Chatwoot rechazó una copia y se apartó (%s)", error)
            self._aviso(
                "⚠️ Una copia no entró a Chatwoot",
                f"Chatwoot la rechazó ({error[:150]}). Quedó guardada en "
                "chatwoot_pendientes (apartada=1); el resto sigue llegando.",
                f"chatwoot-apartada:{pendiente.id}",
            )
            return
        with _sin_ruido():
            self._cola.fallo(pendiente.id, error)
        if tope is not None:
            return  # la rechazó, pero aún le quedan intentos: no es una caída
        ahora = time.monotonic()
        if self._falla_desde is None:
            self._falla_desde = ahora
            log.warning("Chatwoot no recibe (%s): se reintenta sin parar", error)
            self._avisado_caido = False
        elif not self._avisado_caido and (
            ahora - self._falla_desde > AVISAR_TRAS.total_seconds()
        ):
            self._avisado_caido = True
            log.error("Chatwoot lleva un rato sin recibir copias (%s)", error)
            self._aviso(
                "⚠️ Chatwoot no está recibiendo",
                f"Van {self.pendientes()} mensajes guardados esperando. El bot "
                "sigue atendiendo; cuando Chatwoot vuelva, llegan todos en orden.",
                "chatwoot-caido",
            )

    def _volvio(self) -> None:
        if self._falla_desde is None:
            return
        if getattr(self, "_avisado_caido", False):
            self._aviso(
                "✅ Chatwoot volvió",
                "Las copias guardadas están llegando en orden.",
                f"chatwoot-volvio:{int(time.time())}",
            )
            log.info("Chatwoot volvió: llegan las copias guardadas")
        self._falla_desde = None
        self._avisado_caido = False

    def _aviso(self, titulo: str, detalle: str, clave: str) -> None:
        if self._avisar is None:
            return
        try:
            self._avisar(titulo, detalle, clave)
        except Exception as exc:  # pragma: no cover - avisar nunca tumba nada
            log.warning("no se pudo avisar (%s)", exc)

    def _hacer(self, tarea, creada: datetime | None = None) -> None:
        """Una tarea de la cola, sea la que sea."""
        tarde = ""
        if creada is not None and datetime.now(UTC) - creada > TARDE:
            tarde = _cuando_paso(creada)
        if tarea[0] == "estado":
            self._cambiar_estado(tarea[1], tarea[2])
        elif tarea[0] == "seguimiento":
            self._seguir(*tarea[1:])
        elif tarea[0] == "nota":
            texto = f"{tarde} · {tarea[2]}" if tarde else tarea[2]
            self._anotar(tarea[1], texto)
        elif tarea[0] == "asignar":
            self._asignar(tarea[1], tarea[2])
        elif tarea[0] == "quitar":
            self._quitar(tarea[1], tarea[2])
        else:
            self._copiar(*tarea[1:], tarde=tarde)

    def _olvidar(self, conv_id: str) -> None:
        """Deja de recordar qué contacto y qué conversación eran los suyos."""
        with self._candado:
            self._cache.pop(conv_id, None)
            self._nombres.pop(conv_id, None)

    def _copiar(
        self,
        conv_id,
        texto,
        entrante,
        nombre,
        etiquetas,
        atributos,
        adjuntos=(),
        *,
        tarde: str = "",
    ) -> None:
        _, conversacion = self._asegurar(conv_id, nombre)
        archivos = self._bajar(adjuntos)
        if texto == "[adjunto]" and adjuntos and not archivos:
            # No hay archivo que mostrar (una reacción, una ubicación, lo que
            # WhatsApp no deja ver) o no se pudo bajar: se dice QUÉ era.
            from app.domain.models import etiqueta_de_mensaje

            texto = etiqueta_de_mensaje(None, adjuntos)
        # Lo de la clienta, con el token de la persona; lo del bot, firmado por
        # el agente bot «VentaBot».
        token = self._token if entrante else self._token_bot
        # Llega tarde (Chatwoot estuvo caído): que diga a qué hora pasó.
        if archivos and texto == "[adjunto]":
            texto = ""
        if tarde:
            texto = f"{tarde} · {texto}" if texto else tarde
        if not entrante and texto:
            # Se recuerda OTRA VEZ justo antes de copiar: si la copia llega horas
            # después (o la hace otro proceso), el eco que devuelve Chatwoot se
            # sigue reconociendo como del bot y no se le reenvía a la clienta.
            self._recordar(conv_id, texto, si_falta=True)
        if archivos:
            # Las fotos de la clienta se ven COMO FOTOS en Chatwoot, igual que en
            # WhatsApp Business. Antes llegaban como «[adjunto]» y Lía tenía
            # que adivinar si era el comprobante o la regla de la talla.
            self._pedir_con_archivos(
                f"/conversations/{conversacion}/messages",
                {
                    "content": texto,
                    "message_type": "incoming" if entrante else "outgoing",
                    "private": "false",
                },
                archivos,
                token=token,
            )
        elif texto:
            self._pedir(
                "POST",
                f"/conversations/{conversacion}/messages",
                {
                    "content": texto,
                    # En Chatwoot, «incoming» es lo que escribe la clienta y
                    # «outgoing» lo que sale de nuestro lado. Que el bot use
                    # outgoing hace que la conversación se lea igual que si
                    # la hubiera atendido una persona.
                    "message_type": "incoming" if entrante else "outgoing",
                    "private": False,
                    # Esta versión de Chatwoot DESCARTA content_attributes al
                    # crear un mensaje por API: la marca se queda por si otra
                    # la respeta, pero lo que de verdad evita el eco es la
                    # firma del agente bot y `es_eco`.
                    "content_attributes": {"origen": "ventabot"},
                },
                token=token,
            )
        if atributos:
            self._pedir(
                "POST",
                f"/conversations/{conversacion}/custom_attributes",
                {"custom_attributes": atributos},
            )

    # -- el seguimiento: etapa, alertas, ficha, estado, nombre ---------------

    def seguimiento(
        self,
        conversation_id: str,
        seguimiento,
        atributos: dict | None = None,
        *,
        nombre: str = "",
        persona_atendiendo: bool = False,
    ) -> None:
        """Encola poner la conversación al día. Devuelve INMEDIATAMENTE."""
        self._poner(
            [
                "seguimiento",
                conversation_id,
                {
                    "etapa": seguimiento.etapa,
                    "alertas": sorted(seguimiento.alertas),
                },
                dict(atributos or {}),
                nombre,
                persona_atendiendo,
            ]
        )

    def nota(self, conversation_id: str, texto: str) -> None:
        """Una nota PRIVADA para Lía (la clienta no la ve). Firmada «VentaBot»."""
        if (texto or "").strip():
            self._poner(["nota", conversation_id, texto.strip()[:3000]])

    def quitar_etiqueta(self, conversation_id: str, etiqueta: str) -> None:
        self._poner(["quitar", conversation_id, etiqueta])

    def _etiquetas(self, conversacion: int) -> list[str]:
        r = self._pedir("GET", f"/conversations/{conversacion}/labels")
        return list((r or {}).get("payload") or [])

    def _seguir(self, conv_id, s, atributos, nombre, persona_atendiendo) -> None:
        from app.domain.seguimiento import Seguimiento, nuevas_etiquetas

        if isinstance(s, dict):  # así viene de la cola (JSON)
            s = Seguimiento(s["etapa"], frozenset(s.get("alertas") or ()))
        contacto, conversacion = self._asegurar(conv_id, nombre)
        actuales = self._etiquetas(conversacion)
        nuevas = nuevas_etiquetas(actuales, s)
        if sorted(actuales) != nuevas:
            self._pedir(
                "POST", f"/conversations/{conversacion}/labels", {"labels": nuevas}
            )
        if atributos:
            self._pedir(
                "POST",
                f"/conversations/{conversacion}/custom_attributes",
                {"custom_attributes": atributos},
            )
        estado = self._pedir("GET", f"/conversations/{conversacion}") or {}
        self._poner_al_dia_quien_la_lleva(conversacion, estado, s, persona_atendiendo)
        if nombre and contacto and nombre not in self._nombres.get(conv_id, ""):
            # En la lista de Chatwoot se lee «Carlos Pérez», no «+57300…».
            self._pedir("PUT", f"/contacts/{contacto}", {"name": nombre[:80]})
            self._nombres[conv_id] = nombre

    def _anotar(self, conv_id: str, texto: str) -> None:
        _, conversacion = self._asegurar(conv_id, "")
        self._pedir(
            "POST",
            f"/conversations/{conversacion}/messages",
            {"content": texto, "message_type": "outgoing", "private": True},
            token=self._token_bot,
        )

    def _quitar(self, conv_id: str, etiqueta: str) -> None:
        _, conversacion = self._asegurar(conv_id, "")
        actuales = self._etiquetas(conversacion)
        if etiqueta in actuales:
            self._pedir(
                "POST",
                f"/conversations/{conversacion}/labels",
                {"labels": [e for e in actuales if e != etiqueta]},
            )

    # -- quién la lleva: VentaBot o una persona (09/10) ----------------------
    #
    # UN SOLO CRITERIO, igual en el PC y en el celular: la conversación SIEMPRE
    # está asignada a alguien en Chatwoot.
    #   · asignada a VentaBot (el agente bot) → la atiende el bot. Chatwoot la
    #     pone en «Pendiente»: así funciona Chatwoot con los bots, no se puede
    #     tener «Abierta» y asignada al bot a la vez.
    #   · asignada a una persona (Lía, Camilo) → la atiende esa persona y el
    #     bot se calla. Queda en «Abierta».
    # «Sin asignar» no existe: era lo que el celular mostraba como «None».
    # Resolver es otra cosa (cerrar) y no cambia quién la lleva.

    def asignar(self, conversation_id: str, quien: str | int) -> None:
        """Encola asignarla: `"bot"` = VentaBot; un número = esa persona."""
        self._poner(["asignar", conversation_id, quien])

    def _id_del_bot(self) -> int | None:
        """El agente bot del buzón (VentaBot). Se pregunta una vez."""
        if self._bot is None:
            r = self._pedir("GET", f"/inboxes/{self._inbox}/agent_bot") or {}
            self._bot = ((r.get("agent_bot") or {}).get("id")) or None
        return self._bot

    def _asignar(self, conv_id: str, quien) -> None:
        _, conversacion = self._asegurar(conv_id, "")
        if quien == "bot":
            bot = self._id_del_bot()
            if bot is None:
                log.warning(
                    "el buzón no tiene agente bot: no se puede asignar a VentaBot"
                )
                return
            cuerpo = {"assignee_id": bot, "assignee_type": "AgentBot"}
        else:
            cuerpo = {"assignee_id": int(quien)}
        # Si ya la tiene quien debe, no se reasigna: cada asignación deja una
        # línea «asignada a…» en la charla, y Lía escribe muchas veces seguidas.
        meta = (self._pedir("GET", f"/conversations/{conversacion}") or {}).get(
            "meta"
        ) or {}
        tipo = "AgentBot" if quien == "bot" else "User"
        if (
            meta.get("assignee_type") == tipo
            and (meta.get("assignee") or {}).get("id") == cuerpo["assignee_id"]
        ):
            return
        self._pedir("POST", f"/conversations/{conversacion}/assignments", cuerpo)

    def _poner_al_dia_quien_la_lleva(
        self, conversacion: int, estado: dict, s, persona_atendiendo: bool
    ) -> None:
        """Después de cada turno, Chatwoot muestra lo que de verdad pasa."""
        meta = estado.get("meta") or {}
        tipo = meta.get("assignee_type")
        asignada = (meta.get("assignee") or {}).get("id")
        # Una «Resuelta» no se reabre sola: eso desharía lo que se cerró, salvo
        # que haya una alerta que la necesite. (Si la clienta escribe, Chatwoot
        # misma la reabre.)
        if estado.get("status") == "resolved" and not s.abierta:
            return
        if not persona_atendiendo:
            bot = self._id_del_bot()
            if bot is not None and not (tipo == "AgentBot" and asignada == bot):
                self._pedir(
                    "POST",
                    f"/conversations/{conversacion}/assignments",
                    {"assignee_id": bot, "assignee_type": "AgentBot"},
                )
                if tipo == "User":
                    # La tenía una persona y pasaron las 12 h de la pausa: que se
                    # entienda por qué volvió a VentaBot.
                    self._pedir(
                        "POST",
                        f"/conversations/{conversacion}/messages",
                        {
                            "content": "⏰ Pasaron 12 h desde lo último que escribió "
                            "una persona aquí y la clienta volvió a escribir: la "
                            "retomó VentaBot. Para seguir tú, asígnatela o escríbele.",
                            "message_type": "outgoing",
                            "private": True,
                        },
                        token=self._token_bot,
                    )
        # Lo que necesita a una persona se ve como URGENTE en las dos apps (el
        # bot la sigue atendiendo mientras tanto; las carpetas la muestran).
        prioridad = "urgent" if s.abierta else None
        if estado.get("priority") != prioridad:
            self._pedir(
                "POST",
                f"/conversations/{conversacion}/toggle_priority",
                {"priority": prioridad},
            )

    def _cambiar_estado(self, conv_id: str, estado: str) -> None:
        _, conversacion = self._asegurar(conv_id, "")
        self._pedir(
            "POST", f"/conversations/{conversacion}/toggle_status", {"status": estado}
        )

    def _bajar(self, adjuntos) -> list[tuple[str, bytes, str]]:
        """Los bytes de cada adjunto. Uno que falle se salta: los demás siguen."""
        from pathlib import Path

        if not adjuntos:
            return []
        if self._descargar is None and not any(a.get("ruta") for a in adjuntos):
            return []
        archivos = []
        for i, adjunto in enumerate(adjuntos, 1):
            # `ruta` = un archivo NUESTRO (el muestrario, la guía de la talla,
            # el anillo terminado). Se lee del disco y no se baja por el túnel:
            # son los mismos megas que ya salieron hacia WhatsApp.
            ruta = adjunto.get("ruta")
            referencia = adjunto.get("media_id") or adjunto.get("url")
            if not ruta and not referencia:
                continue
            try:
                datos = Path(ruta).read_bytes() if ruta else self._descargar(referencia)
            except Exception as exc:
                log.warning("no se pudo bajar un adjunto para Chatwoot (%s)", exc)
                continue
            if not datos:
                continue
            mime = (adjunto.get("mime_type") or "").split(";")[0].strip()
            archivos.append(
                (
                    _nombre_de_archivo(adjunto, mime, i),
                    datos,
                    mime or "application/octet-stream",
                )
            )
        return archivos

    def _pedir_con_archivos(
        self, ruta: str, campos: dict, archivos, token: str | None = None
    ) -> None:
        import httpx

        r = httpx.post(
            f"{self._base}/api/v1/accounts/{self._cuenta}{ruta}",
            headers={"api_access_token": token or self._token},
            data=campos,
            files=[("attachments[]", archivo) for archivo in archivos],
            timeout=max(self._espera, 30),
        )
        r.raise_for_status()

    def _asegurar(self, conv_id: str, nombre: str) -> tuple[int, int]:
        if conv_id in self._cache:
            return self._cache[conv_id]

        _, _, telefono = conv_id.partition(":")
        contacto = self._buscar_contacto(conv_id) or self._crear_contacto(
            conv_id, telefono, nombre
        )
        conversacion = self._buscar_conversacion(contacto, conv_id) or (
            self._crear_conversacion(contacto, conv_id)
        )
        self._cache[conv_id] = (contacto, conversacion)
        return contacto, conversacion

    def _buscar_contacto(self, conv_id: str) -> int | None:
        r = self._pedir("GET", f"/contacts/search?q={conv_id}")
        for c in (r or {}).get("payload", []):
            if c.get("identifier") == conv_id:
                return c["id"]
        return None

    def _crear_contacto(self, conv_id: str, telefono: str, nombre: str) -> int:
        r = self._pedir(
            "POST",
            "/contacts",
            {
                "inbox_id": self._inbox,
                # El identificador es NUESTRO id de conversación: es lo que
                # deja volver a encontrarla sin depender de cómo Chatwoot
                # normalice un teléfono.
                "identifier": conv_id,
                "name": nombre or f"+{telefono}",
                "phone_number": f"+{telefono}" if telefono.isdigit() else None,
            },
        )
        return (r or {}).get("payload", {}).get("contact", {})["id"]

    def _buscar_conversacion(self, contacto: int, conv_id: str) -> int | None:
        r = self._pedir("GET", f"/contacts/{contacto}/conversations")
        for c in (r or {}).get("payload", []):
            if str(c.get("inbox_id")) == str(self._inbox):
                return c["id"]
        return None

    def _crear_conversacion(self, contacto: int, conv_id: str) -> int:
        r = self._pedir(
            "POST",
            "/conversations",
            {"source_id": conv_id, "inbox_id": self._inbox, "contact_id": contacto},
        )
        return (r or {})["id"]

    def _pedir(
        self, metodo: str, ruta: str, cuerpo: dict | None = None, token: str | None = None
    ):
        import httpx

        url = f"{self._base}/api/v1/accounts/{self._cuenta}{ruta}"
        r = httpx.request(
            metodo,
            url,
            headers={"api_access_token": token or self._token},
            json=cuerpo,
            timeout=self._espera,
        )
        r.raise_for_status()
        return r.json() if r.content else None


class CrmDeMentira:
    """No copia nada. Es lo que hay cuando Chatwoot no está configurado."""

    def __init__(self) -> None:
        self.copias: list[tuple] = []

    def registrar(self, conversation_id: str, texto: str, **kw) -> None:
        self.copias.append((conversation_id, texto, kw))

    def marcar_estado(self, conversation_id: str, estado: str) -> None:
        self.copias.append((conversation_id, f"[estado:{estado}]", {}))

    def es_eco(self, conversation_id: str, texto: str) -> bool:
        return False

    def seguimiento(self, conversation_id: str, seguimiento, atributos=None, **kw):
        self.copias.append((conversation_id, "[seguimiento]", {"s": seguimiento}))

    def nota(self, conversation_id: str, texto: str) -> None:
        self.copias.append((conversation_id, f"[nota] {texto}", {}))

    def quitar_etiqueta(self, conversation_id: str, etiqueta: str) -> None:
        self.copias.append((conversation_id, f"[quitar] {etiqueta}", {}))

    def asignar(self, conversation_id: str, quien: str | int) -> None:
        self.copias.append((conversation_id, f"[asignar] {quien}", {}))
