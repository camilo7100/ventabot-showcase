"""El gestor conversacional: de un mensaje a una respuesta.

════════════════════════════════════════════════════════════════════════════
LOS OCHO TRAMOS
════════════════════════════════════════════════════════════════════════════
    1. CONTEXTO      cargar lo persistente y lo conversacional
    2. INTERPRETAR   [IA]  acto + entidad + atributo + referencia + datos
    3. RESOLVER      «el segundo» -> un id real
    4. PLANIFICAR    (acto, entidad, atributo) -> una acción de la lista
    5. VALIDAR       ¿alcanza? ¿hay ambigüedad? -> se corta aquí o se pasa
    6. EJECUTAR      herramientas deterministas -> ficha de hechos
    7. ACTUALIZAR    contexto, foco, procesos, menciones
    8. REDACTAR      plantilla siempre; el modelo solo con red debajo

Solo el tramo 2 (y opcionalmente el 8) tocan un modelo de lenguaje. Los seis
restantes son Python que se prueba en microsegundos.

════════════════════════════════════════════════════════════════════════════
POR QUÉ ESTO NO ES UN GRAFO
════════════════════════════════════════════════════════════════════════════
El diseño anterior usaba LangGraph con ramas: el router elegía nodo y cada
nodo era un camino. Con una tabla de acciones, la ramificación desaparece: la
tubería es recta y la decisión vive en un `dict`. Un grafo cuyo único camino
es 1→2→3→…→8 es una lista con ceremonia.

Lo que sí aportaba el grafo —que el estado sobreviva entre mensajes— ahora lo
da `ContextoConversacional`, guardado en SQLite. Y guardarlo ahí, y no en un
checkpoint, es lo que va a permitir que un día esto no sea solo reactivo.

════════════════════════════════════════════════════════════════════════════
LA PUERTA PARA CUANDO DEJE DE SER REACTIVO
════════════════════════════════════════════════════════════════════════════
`ejecutar()` arranca en el tramo 1 con un mensaje. `desde_accion()` arranca en
el tramo 5 con una acción ya elegida, sin mensaje y sin modelo.

Ese segundo camino es el que va a usar un trabajo programado el día que el bot
tome la iniciativa: «esta clienta lleva cuatro días sin mandar la talla» es
una acción sobre un proceso abierto, y todo lo que hay del tramo 5 en adelante
—validación, reglas, redacción con red— sirve igual. No hay que construirlo
hoy; hay que no cerrarle la puerta, y esa es la única razón por la que la
firma está partida así.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace

from app.domain import consumo
from app.domain.acciones import Accion, planificar
from app.domain.contexto import ContextoConversacional
from app.domain.decisiones import RegistroDeDecision, registro_del_turno
from app.domain.interpretacion import Interpretacion
from app.domain.models import now_utc
from app.domain.referencias import desde_contexto, resolver
from app.domain.respuesta import Respuesta
from app.domain.validacion import Decision, Disponible, Veredicto, validar

log = logging.getLogger("ventabot.conversacion")


@dataclass
class Turno:
    """Todo lo que se sabe de este turno. Se va llenando tramo a tramo.

    Existe para que cada tramo sea una función con una entrada y una salida
    claras, y para que el log de un turno raro se lea entero de un vistazo en
    vez de reconstruirse de seis sitios.
    """

    conversation_id: str
    texto: str | None = None
    media: list[dict] | None = None
    contexto: ContextoConversacional | None = None
    interpretacion: Interpretacion | None = None
    decision: Decision | None = None
    respuesta: Respuesta | None = None
    #: Por qué se decidió lo que se decidió: capa, confianza, contexto usado,
    #: historial, escalada, costo. Sin texto de la clienta. Ver `domain.decisiones`.
    registro: RegistroDeDecision | None = None

    def resumen(self) -> str:
        partes = []
        if self.interpretacion:
            partes.append(self.interpretacion.resumen())
        if self.decision:
            partes.append(
                f"{self.decision.accion.value}"
                f"[{self.decision.veredicto.value}]"
                + (
                    f" -> {self.decision.objetivo_id}"
                    if self.decision.objetivo_id
                    else ""
                )
            )
        return " | ".join(partes)


class Pipeline:
    """Une los ocho tramos. No sabe de WhatsApp ni de HTTP.

    Recibe colaboradores ya construidos (el intérprete, el ejecutor, el
    redactor) en vez de crearlos: así los tests le pasan dobles y todo corre
    sin red, y así se puede cambiar el modelo de lenguaje sin tocar esto.
    """

    def __init__(self, interprete, mundo, ejecutor, redactor) -> None:
        self._interprete = interprete  # [IA] texto -> Interpretacion
        self._mundo = mundo  # acceso a pedidos, productos, contexto
        self._ejecutor = ejecutor  # Accion -> (Ficha, efectos)
        self._redactor = redactor  # (Accion, Ficha, Decision) -> Respuesta

    # -- camino normal: llega un mensaje -----------------------------------

    def ejecutar(
        self,
        conversation_id: str,
        texto: str | None,
        media: list[dict] | None = None,
        nombre_de_whatsapp: str = "",
    ) -> Turno:
        turno = Turno(conversation_id=conversation_id, texto=texto, media=media)
        inicio = time.perf_counter()
        consumo.abrir_turno()

        # 1. CONTEXTO — el Context Resolver.
        #
        #    Lo guardado se RECONCILIA con la base de datos: lo que apunte a un
        #    pedido cerrado sale del contexto normal, y lo de un pedido activo
        #    no caduca. Un `mundo` sin resolver (un doble de prueba) sigue con
        #    la limpieza por tiempo de siempre.
        guardado = self._mundo.contexto(conversation_id)
        resolver_ctx = getattr(self._mundo, "resolver_contexto", None)
        turno.contexto = resolver_ctx(guardado) if resolver_ctx else guardado.limpiar()

        # 2. INTERPRETAR  [reglas -> modelo básico -> modelo potente, por motivo]
        turno.interpretacion = self._interprete.interpretar(
            texto=texto, media=media, contexto=turno.contexto
        )

        # 2b. Lo que el lector de imágenes quiere que mire una persona.
        #     Va al contexto, no a la respuesta: la clienta no tiene por qué
        #     enterarse de que dudamos de su foto, y Lía sí.
        for nota in turno.interpretacion.notas:
            turno.contexto = turno.contexto.anotar_revision(nota)
        turno.contexto = self._recordar_foto(turno.contexto, turno.interpretacion, media)

        # 3. RESOLVER referencias — Python puro contra el contexto.
        #
        #    Dos catálogos: el OPERATIVO (solo pedidos vivos) y el que además
        #    admite los pedidos históricos que se le acaban de mostrar. El
        #    segundo solo sirve para CONSULTAR: «el segundo» de una lista de
        #    pedidos viejos se puede mirar, pero nunca pagar ni modificar.
        todos = self._mundo.menciones_de_pedidos(conversation_id)
        catalogo = desde_contexto(turno.contexto, todos=todos)
        operativo = replace(
            catalogo, menciones=[m for m in catalogo.menciones if m.tipo != "HISTORICO"]
        )
        resolucion_consulta = resolver(turno.interpretacion.referencia, catalogo)
        resolucion = resolver(turno.interpretacion.referencia, operativo)

        # 4. PLANIFICAR — la tabla decide, no el modelo
        accion = planificar(
            turno.interpretacion.acto,
            turno.interpretacion.entidad,
            turno.interpretacion.atributo,
            trae_datos=turno.interpretacion.datos.hay_algo(),
            hay_proceso=bool(turno.contexto.abiertos()),
        )
        if accion in (Accion.CONSULTAR_PEDIDO, Accion.LISTAR_PEDIDOS) and (
            resolucion_consulta.ok and not resolucion.ok
        ):
            resolucion = resolucion_consulta
        catalogo = operativo

        # 5. VALIDAR — aquí se corta si hay ambigüedad que cueste dinero
        disponible = Disponible(
            pedidos=catalogo.todos,
            pedidos_con_saldo=self._mundo.menciones_con_saldo(conversation_id),
            procesos=[p.id for p in turno.contexto.abiertos()],
            resolucion=resolucion,
        )
        turno.decision = validar(accion, turno.interpretacion, disponible)

        log.info("  %s", turno.resumen())
        if resolucion.origen:
            log.info("  referencia: %s", resolucion.origen)

        # 6 y 7. EJECUTAR y ACTUALIZAR
        if turno.decision.veredicto is Veredicto.EJECUTAR:
            ficha, contexto = self._ejecutor.ejecutar(
                turno.decision, turno.interpretacion, turno.contexto
            )
            turno.contexto = contexto
        else:
            # No se ejecuta nada. La ficha lleva solo lo que hace falta para
            # poder PREGUNTAR bien: los candidatos entre los que elegir.
            ficha, turno.contexto = self._ejecutor.solo_preguntar(
                turno.decision, turno.contexto
            )

        # 8. REDACTAR
        turno.respuesta = self._redactor.redactar(
            turno.decision, ficha, turno.interpretacion, turno.contexto
        )
        if turno.decision.veredicto is Veredicto.ESCALAR:
            turno.respuesta.escalar = True

        # Qué se acaba de contestar. Es lo que impide que el turno siguiente
        # mande el mismo mensaje otra vez (ver `Redactor._sin_repetirse`).
        #
        # `avanzo` dice si este turno trajo algún dato nuevo del anillo. Si lo
        # trajo, la cuenta de insistencias vuelve a cero: la clienta está
        # contestando, aunque no sea justo el hueco que se le preguntó. Sin
        # esto, la cuenta solo subía y el bot acababa contestando «mejor te paso
        # con una personita» a todo, a una clienta que estaba comprando.
        turno.contexto = turno.contexto.registrar_salida(
            turno.respuesta.clave,
            turno.respuesta.huella,
            avanzo=bool(ficha.datos.get("recien")),
        )

        self._mundo.guardar_contexto(turno.contexto)
        turno.registro = registro_del_turno(
            turno, ficha, ms=int((time.perf_counter() - inicio) * 1000)
        )
        log.info("  decision %s", turno.registro.linea())
        return turno

    @staticmethod
    def _recordar_foto(ctx, interp, media):
        """Cuándo llegó la última foto, y cuál quedó por aclarar."""
        cambios: dict = {}
        if media and any(
            (m or {}).get("kind") in ("image", "document", "sticker") for m in media
        ):
            cambios["ultima_foto_en"] = now_utc()
        if interp.foto_pendiente:
            cambios["foto_pendiente"] = interp.foto_pendiente
        elif ctx.foto_pendiente and interp.ruta.motivo == "foto_aclarada":
            cambios["foto_pendiente"] = None
        return ctx.model_copy(update=cambios) if cambios else ctx

    def calentar(self) -> None:
        """Lo que el servidor llama al arrancar (ver `app.api.main`)."""
        calentar = getattr(self._interprete, "calentar", None)
        if callable(calentar):
            calentar()

    # -- camino propositivo: el sistema arranca solo -----------------------

    def desde_accion(
        self, conversation_id: str, accion: Accion, objetivo_id: str | None = None
    ) -> Turno:
        """Entra por el tramo 5, sin mensaje y sin modelo.

        Hoy no lo llama nadie. Existe porque el día que haya recordatorios
        («llevas cuatro días sin mandarme la talla») van a necesitar
        exactamente esto: la misma validación, las mismas reglas y la misma
        redacción con red, sin una clienta que haya escrito nada.

        Dejarlo abierto ahora cuesta veinte líneas. Abrirlo después, cuando la
        lógica esté enredada con «el mensaje entrante», cuesta un rediseño.
        """
        turno = Turno(conversation_id=conversation_id)
        turno.contexto = self._mundo.contexto(conversation_id).limpiar()
        turno.interpretacion = None
        turno.decision = Decision(
            Veredicto.EJECUTAR,
            accion,
            objetivo_id=objetivo_id,
            motivo="iniciada por el sistema, no por la clienta",
        )
        ficha, turno.contexto = self._ejecutor.ejecutar(
            turno.decision, None, turno.contexto
        )
        turno.respuesta = self._redactor.redactar(
            turno.decision, ficha, None, turno.contexto
        )
        turno.contexto = turno.contexto.registrar_salida(
            turno.respuesta.clave, turno.respuesta.huella
        )
        self._mundo.guardar_contexto(turno.contexto)
        return turno
