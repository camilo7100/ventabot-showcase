"""Los recordatorios, dentro del servidor (04/10).

Las reglas —a quién, qué y cuándo— están en `app.domain.recordatorios`, sin
nada de infraestructura. Aquí cada `CADA_S` segundos se miran las charlas de
los últimos días, se decide con esas reglas y se manda por la misma puerta que
todo lo demás (`Container.enviar_a_la_clienta`: outbox + Chatwoot). El
recordatorio entra además en la memoria del bot (como lo que dijo Lía): si
ella contesta «sí», el bot sabe a qué.

Cada envío queda anotado en la base (`RegistroDeRecordatorios`) con su «ancla»
—el último mensaje de ella—: un reinicio nunca le vuelve a escribir, y cuando
ella contesta, la cuenta empieza de cero con su próximo silencio. La plantilla
(el de los 3 días) va como mucho una vez por semana a la misma persona.

`RECORDATORIOS=true` lo enciende; `RECORDATORIO_CON_PLANTILLA=true` suma el de
los 3 días (cuando Meta aprobó la plantilla). `vb recordatorios` dice, sin
mandar nada, a quién le toca qué y a qué hora.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from app.domain import recordatorios as r
from app.domain import recordatorios_por_dias as d
from app.domain.models import Channel, Option, OutboundMessage
from app.domain.numeros_propios import solo_respuesta_inmediata
from app.domain.pricing import formatear_cop

log = logging.getLogger("ventabot.recordatorios")

#: Cada cuánto se mira (los plazos son de horas: 5 min de precisión sobra).
CADA_S = 300.0
#: Los números inventados de las pruebas: nunca se les escribe.
PREFIJO_DE_PRUEBA = "5700000000"
#: Una plantilla (cuesta y es la más «comercial») como mucho una vez por semana.
ENTRE_PLANTILLAS = timedelta(days=7)


def _momento(valor) -> datetime | None:
    if not valor:
        return None
    try:
        m = valor if isinstance(valor, datetime) else datetime.fromisoformat(valor)
    except ValueError:
        return None
    return m if m.tzinfo else m.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Envio:
    conversation_id: str
    numero: int  # 1, 2 o 3 (el 3 con plantilla)
    etapa: str
    ancla: str  # su último mensaje (ISO): identifica el silencio
    cuando: datetime
    texto: str
    nombre: str = ""
    pieza: str = "anillo"
    # -- por días (13/10) --------------------------------------------------
    segmento: str = ""  # S1…S4; vacío: el modo de los dos horarios
    plantilla_nombre: str = ""  # vacío: texto libre (el día 1)
    parametros: dict = field(default_factory=dict, compare=False, hash=False)
    media_url: str = ""  # la foto: su anillo dibujado o uno real grabado
    botones: tuple[str, ...] = ()

    @property
    def plantilla(self) -> bool:
        if self.segmento:
            return bool(self.plantilla_nombre)
        return self.numero == 3


@dataclass(frozen=True)
class PorDias:
    """Lo que el modo por días necesita del negocio (lo arma el contenedor)."""

    #: Nombre lógico de una foto -> su URL pública ("" si no hay URL pública).
    url_de_media: Callable[[str], str]
    #: «$200.000 (1 huellita), $250.000 (2) o $300.000 (3)».
    precios: str
    abono_anillo: int = 60_000
    abono_cadena: int = 65_000
    #: Las cuentas para el abono (las del S4).
    cuentas: str = ""


def plan_por_dias(
    conv, mundo, charlas, registro, nombre_de, ahora, con_plantilla, por_dias: PorDias
) -> Envio | None:
    """El próximo recordatorio por días de una charla (aunque no sea la hora)."""
    fila = charlas.estado_para_recordar(conv)
    if fila is None or fila.get("direccion") != "OUT":
        return None
    if solo_respuesta_inmediata(conv):
        return None  # pruebas y números de la casa: nada programado (19/10)
    ultimo_de_ella = _momento(fila.get("ultimo_entrante"))
    ultimo_del_bot = _momento(fila.get("created_at"))
    if ultimo_de_ella is None or ultimo_del_bot is None:
        return None
    ctx = mundo.contexto(conv)
    if ctx.necesita_persona or mundo.la_atiende_una_persona(conv):
        return None
    from app.domain.asesora import Borrador

    b = Borrador.model_validate(ctx.borrador) if ctx.borrador else None
    pedido = mundo.pedido(b.pedido_id) if b is not None and b.pedido_id else None
    cual = r.etapa(b, pedido.estado if pedido is not None else "")
    seg = d.segmento(cual, b, int(fila.get("mensajes_de_ella") or 0))
    if cual is None or seg is None:
        return None
    ancla = ultimo_de_ella.isoformat()
    otra = registro.ultima_plantilla(conv)
    # Las plantillas de ESTE silencio siguen su calendario; las de otro silencio,
    # como mucho una por semana.
    plantilla_ok = con_plantilla and (
        otra is None or otra > ultimo_de_ella or ahora - otra >= ENTRE_PLANTILLAS
    )
    paso = d.siguiente(
        segmento_de_ella=seg,
        etapa_de_ella=cual,
        ultimo_de_ella=ultimo_de_ella,
        ultimo_del_bot=ultimo_del_bot,
        enviados=registro.enviados(conv, ancla),
        texto_de_ella=fila.get("texto_de_ella") or "",
        ahora=ahora,
        con_plantilla=plantilla_ok,
    )
    if paso is None:
        return None
    nombre = r.primer_nombre((b.nombre_clienta if b else "") or nombre_de(conv))
    pieza = r.pieza_de(b)
    mascota = d.mascota_de(b)
    abono = formatear_cop(
        pedido.anticipo_cop
        if pedido is not None and pedido.anticipo_cop
        else (por_dias.abono_cadena if pieza == "cadena" else por_dias.abono_anillo)
    )
    dibujo = _su_dibujo(mundo, b)
    imagen = dibujo or d.FOTO_DE_UN_ANILLO_GRABADO
    if paso.plantilla:
        valores = d.parametros(
            paso.plantilla, nombre=nombre, mascota=mascota, abono=abono, pieza=pieza
        )
        texto = d.texto_de_la_plantilla(paso.plantilla, valores)
    else:
        valores = {}
        vio_precios = b is None or "MOSTRAR_PRECIOS" in b.mostrado_en
        texto = d.texto_del_dia_1(
            seg,
            cual,
            nombre=nombre,
            mascota=mascota,
            abono=abono,
            precios=por_dias.precios,
            vio_precios=vio_precios,
            con_su_dibujo=bool(dibujo),
            cuentas=por_dias.cuentas if seg == "S4" else "",
        )
    con_foto = not paso.plantilla or paso.plantilla in d.PLANTILLAS
    return Envio(
        conv,
        paso.numero,
        f"{seg}:{cual}",
        ancla,
        paso.cuando,
        texto,
        nombre,
        pieza,
        segmento=seg,
        plantilla_nombre=paso.plantilla,
        parametros=valores,
        media_url=por_dias.url_de_media(imagen) if con_foto else "",
        botones=d.BOTONES,
    )


def _su_dibujo(mundo, b) -> str:
    """El dibujo de SU anillo con los colores que escogió, o "" si no hay."""
    if b is None or not any(h.completa for h in b.huellitas):
        return ""
    try:
        personalizacion, _ = b.a_personalizacion()
        return mundo.previsualizar(personalizacion.huellitas) or ""
    except Exception as exc:  # sin dibujo va la foto de un anillo grabado
        log.warning("recordatorio: no se pudo dibujar su anillo (%s)", exc)
        return ""


def plan_de(
    conv, mundo, charlas, registro, nombre_de, ahora, con_plantilla=False
) -> Envio | None:
    """El próximo recordatorio de una charla (aunque todavía no sea la hora)."""
    fila = charlas.estado_para_recordar(conv)
    if fila is None or fila.get("direccion") != "OUT":
        return None  # lo último lo dijo ella: le toca al bot, no a ella
    if solo_respuesta_inmediata(conv):
        return None  # pruebas y números de la casa: nada programado (19/10)
    ultimo_de_ella = _momento(fila.get("ultimo_entrante"))
    ultimo_del_bot = _momento(fila.get("created_at"))
    if ultimo_de_ella is None or ultimo_del_bot is None:
        return None
    if not r.vale_la_pena(
        int(fila.get("mensajes_de_ella") or 0), fila.get("primer_mensaje") or ""
    ):
        return None  # un mensaje y se fue: no se persigue
    ctx = mundo.contexto(conv)
    if ctx.necesita_persona or mundo.la_atiende_una_persona(conv):
        return None
    from app.domain.asesora import Borrador

    b = Borrador.model_validate(ctx.borrador) if ctx.borrador else None
    pedido = mundo.pedido(b.pedido_id) if b is not None and b.pedido_id else None
    cual = r.etapa(b, pedido.estado if pedido is not None else "")
    if cual is None:
        return None
    ancla = ultimo_de_ella.isoformat()
    otra_plantilla = registro.ultima_plantilla(conv)
    plan = r.siguiente(
        etapa_de_ella=cual,
        ultimo_de_ella=ultimo_de_ella,
        ultimo_del_bot=ultimo_del_bot,
        enviados=registro.enviados(conv, ancla),
        texto_de_ella=fila.get("texto_de_ella") or "",
        ahora=ahora,
        con_plantilla=con_plantilla
        and (otra_plantilla is None or ahora - otra_plantilla >= ENTRE_PLANTILLAS),
    )
    if plan is None:
        return None
    nombre = r.primer_nombre((b.nombre_clienta if b else "") or nombre_de(conv))
    pieza = r.pieza_de(b)
    return Envio(
        conv,
        plan.numero,
        cual,
        ancla,
        plan.cuando,
        r.texto(
            plan.numero,
            cual,
            nombre=nombre,
            pieza=pieza,
            hoy=ahora.astimezone(r.COLOMBIA).date(),
            hora=plan.cuando.astimezone(r.COLOMBIA).hour,
        ),
        nombre,
        pieza,
    )


def planes(
    mundo,
    charlas,
    registro,
    nombre_de,
    ahora=None,
    con_plantilla=False,
    por_dias: PorDias | None = None,
) -> list[Envio]:
    """Los próximos recordatorios de todas las charlas recientes (no manda nada)."""
    ahora = ahora or datetime.now(UTC)
    salida = []
    for conv in charlas.recientes():
        try:
            plan = (
                plan_por_dias(
                    conv,
                    mundo,
                    charlas,
                    registro,
                    nombre_de,
                    ahora,
                    con_plantilla,
                    por_dias,
                )
                if por_dias is not None
                else plan_de(
                    conv, mundo, charlas, registro, nombre_de, ahora, con_plantilla
                )
            )
        except Exception as exc:  # una charla rara no frena las demás
            log.warning("recordatorio: no se pudo mirar %s (%s)", conv, exc)
            continue
        if plan is not None:
            salida.append(plan)
    return sorted(salida, key=lambda e: e.cuando)


def mensaje_de(envio: Envio) -> OutboundMessage:
    canal, _, numero = envio.conversation_id.partition(":")
    comun = {
        "channel": Channel.INSTAGRAM if canal == "ig" else Channel.WHATSAPP,
        "to": numero,
        "text": envio.texto,
        "conversation_id": envio.conversation_id,
        "idempotency_key": (
            f"recordatorio:{envio.conversation_id}:{envio.ancla}:{envio.numero}"
        ),
    }
    if envio.segmento:
        # Por días (13/10): con foto y los tres botones.
        if envio.plantilla_nombre:
            valores = dict(envio.parametros)
            if envio.media_url and envio.plantilla_nombre in d.PLANTILLAS:
                valores["imagen"] = envio.media_url  # la cabecera de la plantilla
            return OutboundMessage(
                kind="template",
                template_name=envio.plantilla_nombre,
                template_params=valores,
                **comun,
            )
        return OutboundMessage(
            kind="options",
            options=[Option(id=b, title=b) for b in envio.botones],
            media_url=envio.media_url or None,
            **comun,
        )
    if envio.plantilla:
        return OutboundMessage(
            kind="template",
            template_name=r.PLANTILLA,
            template_params=r.parametros_de_la_plantilla(envio.nombre, envio.pieza),
            **comun,
        )
    return OutboundMessage(kind="text", **comun)


def mandar(envio: Envio, registro, enviar, anotar_en_la_charla=None) -> bool:
    """Lo manda (outbox + Chatwoot), lo anota y lo deja en la memoria del bot."""
    # Primero se anota: si algo falla después, nunca se manda dos veces.
    if not registro.anotar(envio.conversation_id, envio.ancla, envio.numero, envio.etapa):
        return False
    enviar(envio.conversation_id, mensaje_de(envio))
    if anotar_en_la_charla is not None:
        anotar_en_la_charla(envio.conversation_id, envio.texto)
    log.info(
        "recordatorio %s (%s) a %s", envio.numero, envio.etapa, envio.conversation_id
    )
    return True


def ya_se_le_recordo(mundo, envio: Envio) -> None:
    """Lo que dijo que manda después ya tuvo su recordatorio: no lleva otro, y
    el recordatorio cuenta como una vez pedido (09/10)."""
    # Por días la etapa va con su segmento («S2:despues_talla»).
    que = r.QUE_DE_DESPUES.get(envio.etapa.split(":")[-1])
    if que is None:
        return
    from app.domain.asesora import Borrador

    ctx = mundo.contexto(envio.conversation_id)
    if not ctx.borrador:
        return
    b = Borrador.model_validate(ctx.borrador)
    if que not in b.recordado_despues:
        b.recordado_despues.append(que)
    b.veces_pedido[que] = max(b.veces_pedido.get(que, 0), 1)
    mundo.guardar_contexto(ctx.model_copy(update={"borrador": b.model_dump(mode="json")}))


# ════════════════════════════════════════════════════════════════════════════
# EL JUEZ: la IA lee la charla antes de cada recordatorio (Camilo, 10/10)
# ════════════════════════════════════════════════════════════════════════════
# Las palabras no alcanzan: «Menos pagaría 200 por un anillo en platav», «Miles
# de veces», un sarcasmo, una falta de ortografía. Antes de mandar CUALQUIER
# recordatorio, la IA lee lo último de la charla y dice si escribirle tiene
# sentido. Si no, no sale y la charla queda sin recordatorios. Si la IA falla,
# vale lo de siempre (las palabras de `recordatorios.no_quiere`).

JUEZ = (
    "Decides si a una clienta de Luna Joyas (anillos de plata con las huellitas "
    "de su mascota, por WhatsApp) se le manda un recordatorio amable, porque dejó "
    "de contestar.\n\n"
    "escribirle = false si en la conversación ella mostró CUALQUIER desinterés, por "
    "pequeño o indirecto que sea, aunque esté mal escrito, sea corto o con sarcasmo: "
    "no le gusta el producto, el material, el precio o el diseño; dice que no lo va "
    "a pedir, que está caro, que solo estaba mirando o preguntando, que no está "
    "interesada, que no le escriban o que ya lo dijo; lo deja para otro mes o para "
    "«más adelante» sin fecha; o ya se despidió. También false si la asesora ya le "
    "pidió disculpas por insistir o le dijo que no le escribiría más.\n\n"
    "escribirle = true en todo lo demás: quedarse callada NO es desinterés, es justo "
    "para lo que es el recordatorio (preguntó el precio y no volvió, estaba armando "
    "su anillo, iba a medir su talla, iba a pagar, dijo «mañana» o «en la tarde»). "
    "Solo false si hay una señal de desinterés como las de arriba, aunque sea "
    "pequeña; si después de esa señal ella retomó con interés (escogió algo, "
    "preguntó cómo pagar), cuenta lo último."
)


class Veredicto(BaseModel):
    escribirle: bool = Field(description="¿Se le manda el recordatorio?")
    motivo: str = Field(description="Por qué, en una frase corta")


def charla_para_el_juez(charla: list[dict], maximo: int = 14) -> str:
    lineas = []
    for m in charla[-maximo:]:
        quien = "CLIENTA" if m.get("de") == "clienta" else "ASESORA"
        lineas.append(f"{quien}: {(m.get('texto') or '').strip()[:400]}")
    return "\n".join(lineas)


def juez_con(llm):
    """El juez sobre un LLM (`LLMPort`). Devuelve (escribirle, motivo), o None si
    la IA no contestó (entonces mandan las palabras)."""

    def juzgar(charla: list[dict]) -> tuple[bool, str] | None:
        try:
            v = llm.extract(JUEZ, charla_para_el_juez(charla), Veredicto)
        except Exception as exc:  # la IA caída no frena ni manda de más
            log.warning("el juez de recordatorios no contestó (%s)", exc)
            return None
        return bool(v.escribirle), (v.motivo or "")[:200]

    return juzgar


def no_le_interesa(mundo, conv: str, motivo: str) -> None:
    """Sin recordatorios en esta charla hasta que ella retome el pedido."""
    from app.domain.asesora import Borrador

    ctx = mundo.contexto(conv)
    b = Borrador.model_validate(ctx.borrador) if ctx.borrador else Borrador()
    b.sin_recordatorios = True
    mundo.guardar_contexto(ctx.model_copy(update={"borrador": b.model_dump(mode="json")}))
    log.info("recordatorio a %s: NO (%s)", conv, motivo)


class Recordador:
    """La vuelta automática: cada `intervalo_s`, manda lo que ya toca."""

    def __init__(
        self,
        mundo,
        charlas,
        registro,
        enviar,
        *,
        nombre_de=lambda conv: "",
        anotar_en_la_charla=None,
        intervalo_s: float = CADA_S,
        en_el_hilo=None,
        ocupada=lambda conv: False,
        ventana_abierta=lambda conv: True,
        con_plantilla: bool = False,
        juez=None,
        por_dias: PorDias | None = None,
    ) -> None:
        self._mundo = mundo
        self._charlas = charlas
        self._registro = registro
        self._enviar = enviar
        self._nombre_de = nombre_de
        self._anotar = anotar_en_la_charla
        self._intervalo = intervalo_s
        #: Para no escribirle mientras el bot le está contestando (mismo hilo
        #: de los turnos: `Agrupador.en_el_hilo`).
        self._en_el_hilo = en_el_hilo
        self._ocupada = ocupada
        #: La ventana de 24 h de verdad (por cuándo ESCRIBIÓ ella, no por
        #: cuándo llegó). Sin plantilla, solo se recuerda con ella abierta.
        self._ventana_abierta = ventana_abierta
        self._con_plantilla = con_plantilla
        #: La IA que lee la charla antes de cada recordatorio (`juez_con`).
        self._juez = juez
        #: Con esto, el modo POR DÍAS (13/10); sin esto, el de los dos horarios.
        self._por_dias = por_dias
        self._tarea: asyncio.Task | None = None

    def planes(self, ahora: datetime | None = None) -> list[Envio]:
        return planes(
            self._mundo,
            self._charlas,
            self._registro,
            self._nombre_de,
            ahora,
            self._con_plantilla,
            self._por_dias,
        )

    def _plan_de(self, conv: str, ahora: datetime) -> Envio | None:
        if self._por_dias is not None:
            return plan_por_dias(
                conv,
                self._mundo,
                self._charlas,
                self._registro,
                self._nombre_de,
                ahora,
                self._con_plantilla,
                self._por_dias,
            )
        return plan_de(
            conv,
            self._mundo,
            self._charlas,
            self._registro,
            self._nombre_de,
            ahora,
            self._con_plantilla,
        )

    def una_vuelta(self, ahora: datetime | None = None) -> int:
        ahora = ahora or datetime.now(UTC)
        mandados = 0
        for envio in self.planes(ahora):
            if envio.cuando > ahora or self._ocupada(envio.conversation_id):
                continue
            # Se vuelve a mirar justo antes: pudo escribir en este instante.
            otra_vez = self._plan_de(envio.conversation_id, ahora)
            if otra_vez is None or otra_vez.numero != envio.numero:
                continue
            if not otra_vez.plantilla and not self._ventana_abierta(
                envio.conversation_id
            ):
                # 17/10: a las que Meta les entregó atrasado, el silencio se
                # contaba desde que LLEGÓ su mensaje. El texto quedaba en la
                # outbox esperando una ventana cerrada hacía días, y habría
                # salido pegado a la respuesta del bot el día que contestara.
                continue
            if self._juez is not None:
                veredicto = self._juez(self._mundo.contexto(envio.conversation_id).charla)
                if veredicto is not None and not veredicto[0]:
                    no_le_interesa(self._mundo, envio.conversation_id, veredicto[1])
                    continue
            if mandar(otra_vez, self._registro, self._enviar, self._anotar):
                mandados += 1
                ya_se_le_recordo(self._mundo, otra_vez)
        return mandados

    async def _bucle(self) -> None:
        while True:
            await asyncio.sleep(self._intervalo)
            try:
                if self._en_el_hilo is not None:
                    await self._en_el_hilo(self.una_vuelta)
                else:
                    self.una_vuelta()
            except Exception:  # nunca tumba el servidor
                log.exception("la vuelta de recordatorios falló")

    def arrancar(self) -> None:
        if self._tarea is None:
            self._tarea = asyncio.create_task(self._bucle(), name="recordatorios")

    async def parar(self) -> None:
        if self._tarea is not None:
            self._tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tarea
            self._tarea = None
