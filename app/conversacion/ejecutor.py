"""Tramo 6: las herramientas. Aquí sí se toca la base de datos.

Cada acción tiene su método y ninguno recibe texto libre: reciben una
`Decision` ya validada y una `Interpretacion` con campos tipados. El modelo no
llega hasta aquí.

Todos devuelven lo mismo: una `Ficha` con los datos reales y el contexto
actualizado. La ficha es lo único que el redactor va a poder usar, así que un
dato que no salga de aquí es un dato que el bot no puede decir — incluso si es
verdad. Preferimos una respuesta escueta a una inventada.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from app.domain.contexto import (
    ContextoConversacional,
    Proceso,
    TipoProceso,
)
from app.domain.envio import DatosDeEnvio
from app.domain.faq import ENVIO_NACIONAL_COP
from app.domain.hechos import Ficha
from app.domain.interpretacion import Acto, Atributo, Interpretacion
from app.domain.operativo import pendiente_de_pago
from app.domain.order_state import ETIQUETA_CLIENTE, OrderState
from app.domain.order_state import TERMINALES as TERMINALES_HISTORIAL
from app.domain.personalizacion import ColorCircon, Huellita, Personalizacion
from app.domain.pricing import cotizar, formatear_cop
from app.domain.validacion import Decision

log = logging.getLogger("ventabot.ejecutor")

#: Dónde está el pedido cuando lo que falta es que ella pague el abono.
ESPERANDO_EL_ABONO = frozenset(
    {
        OrderState.BORRADOR,
        OrderState.COTIZADO,
        OrderState.CONFIRMADO,
        OrderState.ESPERANDO_ANTICIPO,
    }
)
#: …y cuando lo que falta es el saldo, ya con el anillo hecho.
ESPERANDO_EL_SALDO = frozenset({OrderState.PRODUCCION_LISTA, OrderState.ESPERANDO_SALDO})
#: El anillo ya existe: lo que se pague ahora es el saldo, no el abono.
YA_SE_FABRICO = ESPERANDO_EL_SALDO | {OrderState.SALDO_PAGADO}


class Ejecutor:
    def __init__(self, mundo, desempate=None) -> None:
        self._m = mundo
        #: `(motivo, resultado, filtro) -> Order | None`. Solo para la búsqueda
        #: histórica que sale ambigua; lo arma el contenedor con el modelo
        #: potente. Sin él, se le pregunta a la clienta cuál es.
        self._desempate = desempate

    # -- entrada ------------------------------------------------------------

    def ejecutar(
        self,
        decision: Decision,
        interp: Interpretacion | None,
        ctx: ContextoConversacional,
    ) -> tuple[Ficha, ContextoConversacional]:
        # La ciudad se apunta SIEMPRE, sea cual sea la acción. Una clienta
        # dice de dónde es cuando le da la gana —«hola, soy de Bogotá», antes
        # de preguntar nada— y si solo se guardara al anotar datos de una
        # compra, ese caso (el más común) se perdería y se le cobraría el
        # flete nacional a alguien que vive a veinte minutos de la bodega.
        ctx = self._recordar_ciudad(interp, ctx)

        metodo = getattr(self, f"_{decision.accion.value.lower()}", None)
        if metodo is None:
            log.warning("acción sin herramienta: %s", decision.accion.value)
            return Ficha(), ctx
        return metodo(decision, interp, ctx)

    @staticmethod
    def _recordar_ciudad(interp, ctx):
        ciudad = interp.datos.ciudad if interp else None
        if not ciudad or ctx.ciudad == ciudad:
            return ctx
        return ctx.model_copy(update={"ciudad": ciudad})

    def solo_preguntar(
        self, decision: Decision, ctx: ContextoConversacional
    ) -> tuple[Ficha, ContextoConversacional]:
        """No se ejecuta nada, pero hay que poder preguntar BIEN.

        La ficha lleva los candidatos para poder nombrarlos («¿el del taller o
        el que espera saldo?»). Un «¿cuál?» a secas obliga a la clienta a
        repetir lo que ya dijo, y es donde se abandonan las conversaciones.
        """
        ficha = Ficha()
        for i, m in enumerate(decision.candidatos, start=1):
            ficha.datos[f"opcion_{i}"] = m.etiqueta
        if decision.candidatos:
            ctx = ctx.mostrar([("PEDIDO", m.id, m.etiqueta) for m in decision.candidatos])
        return ficha, ctx

    # -- solo leen ----------------------------------------------------------

    def _saludar(self, d, i, ctx):
        return Ficha(), ctx

    def _charlar(self, d, i, ctx):
        return Ficha(), ctx

    def _no_entendi(self, d, i, ctx):
        return Ficha(), ctx

    def _llamar_humano(self, d, i, ctx):
        return Ficha(), ctx

    def _mostrar_producto(self, d, i, ctx):
        """El catálogo comercial. Los precios salen del CSV, nunca del modelo."""
        ficha = Ficha()
        productos = sorted(
            (p for p in self._m.productos() if p.categoria == "anillos"),
            key=lambda p: p.huellitas or 0,
        )
        for p in productos:
            ficha.montos.append(formatear_cop(p.precio_cop))
            ficha.datos[f"precio_{p.huellitas}"] = formatear_cop(p.precio_cop)
        if productos:
            ficha.datos["abono"] = formatear_cop(productos[0].anticipo_fijo_cop or 0)
            ficha.datos["dias"] = str(productos[0].dias_produccion)
            ficha.datos["dias_max"] = str(productos[0].dias_produccion_max or 15)
            ficha.montos.append(formatear_cop(productos[0].anticipo_fijo_cop or 0))
        return ficha, ctx

    def _mostrar_imagenes(self, d, i, ctx):
        return Ficha(), ctx

    def _responder_duda(self, d, i, ctx):
        """La respuesta sale palabra por palabra de `faq.py`, no del modelo."""
        from app.domain.faq import Pregunta, responder

        ficha = Ficha()
        mapa = {
            Atributo.MATERIAL: Pregunta.MATERIAL,
            Atributo.GARANTIA: Pregunta.GARANTIA,
            Atributo.COSTO_ENVIO: Pregunta.ENVIO,
            Atributo.MEDIOS_DE_PAGO: Pregunta.MEDIOS_DE_PAGO,
            Atributo.CONTRAENTREGA: Pregunta.CONTRAENTREGA,
            Atributo.TIEMPO: Pregunta.TIEMPO_ENTREGA,
            Atributo.COMO_MEDIR: Pregunta.COMO_MEDIR_TALLA,
            Atributo.COLOR_DISPONIBLE: Pregunta.COLOR_DORADO,
            Atributo.VALOR: Pregunta.POR_QUE_VALE,
            Atributo.CONFIANZA: Pregunta.ES_CONFIABLE,
            Atributo.AJUSTE: Pregunta.SI_NO_ME_QUEDA,
        }
        atributo = i.atributo if i else Atributo.NINGUNO
        pregunta = mapa.get(atributo)
        # «¿Cuánto vale el envío?» contestado con el valor nacional cuando la
        # clienta YA dijo que es de Bogotá es una respuesta peor que la de un
        # humano, y encima le cobra de más. Si la ciudad está anotada, manda.
        envio = formatear_cop(self._m.envio_a(self._ciudad_de(ctx)))
        if pregunta is not None and (texto := responder(pregunta, envio=envio)):
            ficha.literales.append(texto)
        return ficha, ctx

    @staticmethod
    def _ciudad_de(ctx) -> str | None:
        """La ciudad que la clienta haya dicho, la haya dicho cuando la dijera.

        Sale del contexto y no del cliente guardado porque en la primera
        conversación todavía no hay cliente con dirección: lo único que hay es
        lo que acaba de escribir.
        """
        if ctx.ciudad:
            return ctx.ciudad
        for proceso in ctx.abiertos(TipoProceso.COMPRA):
            if ciudad := proceso.datos.get("ciudad"):
                return str(ciudad)
        return None

    def _explicar_como_medir(self, d, i, ctx):
        from app.domain.faq import Pregunta, responder

        return Ficha(literales=[responder(Pregunta.COMO_MEDIR_TALLA) or ""]), ctx

    def _explicar_como_pagar(self, d, i, ctx):
        """Los medios de pago — o LA cuenta, si nombró una.

        Decir «bancolombia» después de ver la lista no es volver a preguntar
        por la lista: es elegir. Repetírsela entera es la respuesta más
        robótica que puede dar un sistema, y es exactamente lo que hacía.
        """
        from app.domain.faq import (
            Pregunta,
            datos_de_cuenta,
            datos_para_transferir,
            responder,
        )

        medio = i.datos.medio_pago if i else None
        if medio and (cuenta := datos_de_cuenta(medio)):
            ficha = Ficha(literales=[cuenta])
            ficha.datos["medio"] = medio
            if "[POR DEFINIR]" in cuenta:
                # Honesto antes que inventado: una cuenta equivocada es plata
                # que se va a otro lado y no vuelve.
                ficha.datos["cuenta_sin_definir"] = "si"
            return ficha, ctx

        # Sin medio concreto: la lista Y LOS NÚMEROS.
        #
        # «¿Dónde pago?» contestado con una lista de nombres de bancos y
        # ningún número obliga a preguntar otra vez. La lista dice qué se
        # puede; las cuentas dejan hacerlo.
        literales = [responder(Pregunta.MEDIOS_DE_PAGO) or ""]
        if cuentas := datos_para_transferir():
            literales.append(cuentas)
        return Ficha(literales=literales), ctx

    def _sugerir_combinacion(self, d, i, ctx):
        """Tres combinaciones con nombre y con foto. Y la última palabra es suya.

        Es la acción de servicio del bot: delante de ciento noventa y seis
        combinaciones posibles mucha gente no elige, y quien no elige no
        compra. Tres opciones concretas quitan esa parálisis.

        Se guardan en el proceso para poder resolver el «la segunda» del
        mensaje siguiente sin volver a calcular nada.
        """
        from app.domain.sugerencias import COMBINACIONES

        ficha = Ficha()
        for n, sugerencia in enumerate(COMBINACIONES, start=1):
            ficha.datos[f"combo_{n}"] = sugerencia.describir()
            vista = self._m.previsualizar([sugerencia.huellita])
            if vista:
                ficha.datos[f"vista_{n}"] = vista

        abiertos = ctx.abiertos(TipoProceso.COMPRA)
        if abiertos:
            proceso = abiertos[0].con(sugeridas=[s.clave for s in COMBINACIONES])
            ctx = ctx.guardar_proceso(proceso)
        return ficha, ctx

    def _explicar_que_sigue(self, d, i, ctx):
        """«¿Y ahora qué hago?». La pregunta que decide la venta.

        La respuesta correcta depende del estado del pedido y de nada más:
        antes del abono es el abono; después es esperar; al final es el saldo.
        Se calcula, no se adivina — y por eso los datos de la cuenta salen de
        `faq`, que es la fuente única, y no de una frase escrita aquí.
        """
        from app.domain.faq import datos_para_transferir

        pedido = self._m.pedido(d.objetivo_id) if d.objetivo_id else None
        if pedido is None:
            return Ficha(), ctx

        ficha = self._ficha_de_pedido(pedido)
        estado = OrderState(pedido.estado)
        if estado in ESPERANDO_EL_ABONO:
            ficha.datos["que_falta"] = "abono"
            ficha.datos["cuanto"] = formatear_cop(pedido.anticipo_cop)
        elif estado in ESPERANDO_EL_SALDO:
            ficha.datos["que_falta"] = "saldo"
            ficha.datos["cuanto"] = formatear_cop(pendiente_de_pago(pedido))
        else:
            ficha.datos["que_falta"] = "nada"
        if ficha.datos["que_falta"] != "nada":
            ficha.literales.append(datos_para_transferir())
        return ficha, ctx.enfocar("PEDIDO", pedido.id)

    def _listar_pedidos(self, d, i, ctx):
        return self._consultar_pedido(d, i, ctx)

    def _consultar_pedido(self, d, i, ctx):
        """Un pedido concreto, o todos si no se señaló ninguno.

        Cuando se listan varios, se registran como menciones: es lo que hace
        que el «¿y el segundo?» del mensaje siguiente se pueda resolver.
        """
        ficha = Ficha()
        if d.objetivo_id:
            pedido = self._m.pedido(d.objetivo_id)
            if pedido is None:
                return ficha, ctx
            # Un pedido CERRADO se puede mirar, pero no pasa a ser «de lo que se
            # está hablando»: el foco es contexto operativo, y ese es solo de
            # lo que sigue vivo.
            if OrderState(pedido.estado) not in TERMINALES_HISTORIAL:
                ctx = ctx.enfocar("PEDIDO", pedido.id)
            return self._ficha_de_pedido(pedido), ctx

        pedidos = self._m.pedidos_de(ctx.conversation_id)
        if not pedidos:
            return ficha, ctx
        if len(pedidos) == 1:
            ctx = ctx.enfocar("PEDIDO", pedidos[0].id)
            return self._ficha_de_pedido(pedidos[0]), ctx

        from app.conversacion.mundo import etiquetar

        ctx = ctx.mostrar([("PEDIDO", o.id, etiquetar(o)) for o in pedidos])
        for n, o in enumerate(pedidos, start=1):
            ficha.datos[f"pedido_{n}"] = etiquetar(o)
        ficha.datos["cuantos"] = str(len(pedidos))
        return ficha, ctx

    def _ficha_de_pedido(self, pedido) -> Ficha:
        debe = pendiente_de_pago(pedido)
        ficha = Ficha(
            montos=[
                formatear_cop(pedido.total_cop),
                formatear_cop(debe),
                formatear_cop(pedido.anticipo_cop),
                formatear_cop(pedido.saldo_cop),
            ],
            datos={
                "codigo": pedido.codigo,
                "estado": ETIQUETA_CLIENTE[OrderState(pedido.estado)],
                "total": formatear_cop(pedido.total_cop),
                "debe": formatear_cop(debe),
                # El del pedido, congelado el día que se cotizó. Enseñar el
                # de hoy sería cambiarle el precio a alguien que ya compró.
                "envio": formatear_cop(
                    pedido.envio_contraentrega_cop or ENVIO_NACIONAL_COP
                ),
            },
        )
        if pedido.items:
            ficha.datos["producto"] = pedido.items[0].nombre
            if desc := pedido.items[0].personalizacion.describir():
                ficha.literales.append(desc)
        return ficha

    # -- construyen un pedido ----------------------------------------------

    def _iniciar_compra(self, d, i, ctx):
        """Abre una compra y le pega de una vez todo lo que la frase traía.

        «Quiero un anillo de dos huellitas talla 8» abre el proceso Y anota
        las dos cosas. Volver a preguntar «¿cuántas huellitas?» después de eso
        es el defecto más irritante que puede tener un bot.

        ════════════════════════════════════════════════════════════════════
        SI YA HAY UNA COMPRA A MEDIAS, ES ESA. NO SE ABRE OTRA.
        ════════════════════════════════════════════════════════════════════
        Esto abría un proceso nuevo cada vez, y en una conversación real se
        partió la venta en dos: «talla 6» fue a una compra y «me gustaría en
        negro» abrió otra. Desde ahí la talla quedó huérfana en un proceso que
        nadie volvió a tocar, las dos mitades pedían la misma cosa, y todo lo
        que llegaba después acababa en «mejor te paso con una personita» — la
        conversación se jamó para siempre.

        Una clienta que está describiendo su anillo NO está empezando otro
        anillo. El segundo anillo de verdad llega por otros dos caminos, y
        ninguno pasa por aquí: `AGREGAR` («también quiero otro») y la `cola`
        de `huellitas_extra` («uno de una huella y otro de dos»).

        Solo se reutiliza la que sigue teniendo huecos. Una compra ya cerrada
        —con su pedido creado— sí tiene que dejar sitio a la siguiente.
        """
        a_medias = [p for p in ctx.abiertos(TipoProceso.COMPRA) if p.pendientes]

        # «Comencemos de 0»: lo que estuviera a medias NO se le pega. Se cierra
        # (sigue sin ser un pedido, así que no se pierde nada del negocio) y se
        # abre una compra limpia. En la prueba con Meta, esa frase le volvió a
        # enseñar un anillo ya despachado.
        if i is not None and i.datos.empezar_de_cero:
            for viejo in a_medias:
                ctx = ctx.cerrar_proceso(viejo.id)
            a_medias = []

        proceso = a_medias[0] if a_medias else Proceso(tipo=TipoProceso.COMPRA)
        retomada = bool(a_medias) and self._se_retoma(a_medias[0], ctx)
        proceso, ctx = self._anotar_en(proceso, i, ctx)
        ficha = self._ficha_de_proceso(proceso)
        if retomada:
            ficha.datos["retomada"] = "si"
        return ficha, ctx

    def _anotar_datos(self, d, i, ctx):
        """Un dato suelto. Va al proceso que lo esté esperando.

        Si hay varias compras abiertas que podrían recibirlo, la validación ya
        habría cortado antes de llegar aquí. Aquí solo queda el caso claro.

        A QUÉ PROCESO VA lo decide `_proceso_destino`, mirando el estado REAL
        del pedido: unos colores nuevos no se le pegan a un anillo que ya está
        fabricado, y una talla que llega a los veinte días sí encuentra su
        pedido aunque el proceso de la conversación ya haya caducado.
        """
        proceso, ctx, aviso = self._proceso_destino(i, ctx)
        if aviso:
            return Ficha(datos=aviso), ctx
        retomada = not proceso.datos.get("pedido_id") and self._se_retoma(proceso, ctx)
        proceso, ctx = self._anotar_en(proceso, i, ctx)
        ficha = self._ficha_de_proceso(proceso)
        if retomada and proceso.datos.get("_recien"):
            ficha.datos["retomada"] = "si"
        return ficha, ctx

    #: Datos del DISEÑO del anillo, frente a los de entrega.
    DISENO = frozenset(
        {"huellitas", "colores", "correccion", "color_a_medias", "grabado"}
    )
    #: Qué campos de la compra corresponden a cada etiqueta de `_recien`.
    CAMPO_DE: ClassVar[dict[str, str]] = {
        "huellitas": "huellitas",
        "talla": "talla",
        "talla_de_foto": "talla",
        "talla_de_medida": "talla",
        "colores": "colores",
        "correccion": "colores",
        "color_a_medias": "colores",
        "grabado": "grabado",
        "nombre": "nombre",
        "ciudad": "ciudad",
        "direccion": "direccion",
    }

    #: Cuánto tiempo sin tocar una compra a medias para avisar de que se retoma.
    MINUTOS_PARA_RETOMAR = 30

    def _se_retoma(self, proceso: Proceso, ctx) -> bool:
        """¿Se está volviendo a una compra de antes, sin que se la acabemos de
        preguntar? Entonces se le dice, para que no se entere por el resumen.

        Salió de la prueba con Meta: «Me gustaría pedir 1» completó al instante
        un anillo con colores, nombres, talla y dirección de pruebas de días
        anteriores, sin ningún aviso.
        """
        from datetime import UTC, datetime, timedelta

        if (ctx.ultima_clave or "").startswith("pregunta:"):
            return False
        tocado = (
            proceso.tocado
            if proceso.tocado.tzinfo
            else proceso.tocado.replace(tzinfo=UTC)
        )
        tiene_algo = any(
            proceso.datos.get(k) for k in ("colores", "grabados", "talla", "direccion")
        )
        return tiene_algo and datetime.now(UTC) - tocado > timedelta(
            minutes=self.MINUTOS_PARA_RETOMAR
        )

    def _proceso_destino(self, i, ctx) -> tuple[Proceso, ContextoConversacional, dict]:
        """El proceso de compra al que va este dato. (proceso, ctx, aviso).

        En orden:
          1. la compra a medias más reciente;
          2. la compra de un pedido ACTIVO, si el dato le puede corresponder
             (unos colores nuevos a un anillo ya fabricado son otro anillo,
             salvo que diga que quiere cambiarlo);
          3. un pedido activo sin proceso en la conversación (volvió días
             después): se reconstruye el proceso desde el PEDIDO, que es la
             verdad, no desde la memoria del chat;
          4. una compra nueva.

        `aviso` no vacío significa que no se puede decidir solo a qué pedido va
        (tiene varios activos): se deja para una persona, sin escribir nada.
        """
        from app.domain.cambios import SIN_FABRICAR

        datos = i.datos if i is not None else None
        abiertos = ctx.abiertos(TipoProceso.COMPRA)
        a_medias = [p for p in abiertos if p.pendientes]
        if a_medias:
            return a_medias[0], ctx, {}

        trae_diseno = bool(
            datos
            and (
                datos.huellitas
                or datos.parejas
                or datos.color_corazon
                or datos.color_dedos
                or datos.colores_sueltos
                or datos.nombres
                or datos.sin_grabado
            )
        )
        # Solo un MODIFICAR explícito apunta el diseño a un anillo ya pagado; y
        # aun así la política de cambios decide si se escribe (casi nunca).
        quiere_cambiar = i is not None and i.acto is Acto.MODIFICAR

        for proceso in abiertos:
            pedido_id = proceso.datos.get("pedido_id")
            pedido = self._m.pedido(pedido_id) if pedido_id else None
            if pedido is None:
                return proceso, ctx, {}  # sin pedido todavía: la de siempre
            sin_fabricar = OrderState(pedido.estado) in SIN_FABRICAR
            if trae_diseno and not sin_fabricar and not quiere_cambiar:
                # Un anillo ya pagado o fabricado no recibe colores nuevos por
                # la puerta de atrás: eso es otro anillo.
                return Proceso(tipo=TipoProceso.COMPRA), ctx, {}
            # El PEDIDO manda sobre la memoria del chat: si el proceso guardado
            # quedó con menos datos (o viejos), se rellena desde el pedido. En
            # la prueba E2E, una clienta que volvió a los 20 días con «7» vio
            # cómo el bot le preguntaba colores que su pedido ya tenía.
            desde_pedido = self._proceso_desde_pedido(pedido)
            datos = {
                **desde_pedido.datos,
                **{k: v for k, v in proceso.datos.items() if k.startswith("_")},
            }
            refrescado = proceso.model_copy(
                update={"datos": datos, "pedido_id": pedido.id}
            )
            refrescado = refrescado.model_copy(
                update={"faltan": self._faltan(refrescado)}
            )
            return refrescado, ctx, {}

        activos = self._m.pedidos_de(ctx.conversation_id)
        if activos and not (trae_diseno and not quiere_cambiar):
            candidatos = activos
            if datos is not None and datos.talla is not None:
                sin_talla = [
                    o
                    for o in activos
                    if any(x.personalizacion.talla is None for x in o.items)
                ]
                candidatos = sin_talla if len(sin_talla) == 1 else activos
            if len(candidatos) == 1:
                proceso = self._proceso_desde_pedido(candidatos[0])
                return proceso, ctx.guardar_proceso(proceso), {}
            codigos = ", ".join(o.codigo for o in candidatos[:4])
            ctx = ctx.anotar_revision(
                f"La clienta mandó un cambio ({i.resumen() if i else ''}) y tiene varios "
                f"pedidos activos ({codigos}): confirmar con ella a cuál va."
            )
            return Proceso(tipo=TipoProceso.COMPRA), ctx, {"cambio_varios": codigos}
        return Proceso(tipo=TipoProceso.COMPRA), ctx, {}

    def _proceso_desde_pedido(self, pedido) -> Proceso:
        """El proceso de compra de un pedido que existe, leído del PEDIDO.

        Es lo que hace que una clienta que vuelve a los veinte días con «talla
        7» encuentre su anillo aunque la conversación ya lo hubiera olvidado.
        """
        item = pedido.items[0] if pedido.items else None
        p = item.personalizacion if item else None
        datos: dict = {
            "pedido_id": pedido.id,
            "codigo": pedido.codigo,
            "huellitas": len(p.huellitas) if p and p.huellitas else None,
            "colores": [
                {"corazon": h.corazon.value, "dedos": h.dedos.value}
                for h in (p.huellitas if p else [])
            ],
            "grabados": list(p.grabados) if p else [],
            "sin_grabado": bool(p.sin_grabado) if p else False,
            "talla": p.talla if p else None,
            # La marca de «confirmar la talla antes de fundir» NO se puede
            # perder al reconstruir: sin ella, el siguiente cambio la borraría.
            "talla_revisar": bool(p.talla_revisar) if p else None,
            "talla_motivo": p.talla_motivo if p else None,
            "nombre_envio": pedido.envio.nombre,
            "ciudad": pedido.envio.ciudad,
            "direccion": pedido.envio.direccion,
            "telefono": pedido.envio.telefono,
        }
        if p and p.talla is None:
            # Nació sin talla a propósito: no se le vuelve a preguntar como si
            # la compra estuviera a medias, se espera a que la mande.
            datos["sin_talla"] = True
        if not datos["huellitas"] and item is not None:
            producto = self._m.producto(item.sku)
            datos["huellitas"] = getattr(producto, "huellitas", None) or 1
        datos = {k: v for k, v in datos.items() if v not in (None, "")}
        proceso = Proceso(tipo=TipoProceso.COMPRA, pedido_id=pedido.id, datos=datos)
        return proceso.model_copy(update={"faltan": self._faltan(proceso)})

    def _anotar_en(self, proceso: Proceso, i, ctx):
        datos = i.datos if i else None
        if datos is None:
            return proceso, ctx.guardar_proceso(proceso)

        anterior = proceso
        nuevo = dict(proceso.datos)
        # Qué llegó EN ESTE MENSAJE. Es lo que se le repite de vuelta, y solo
        # eso: hacer eco de todo lo acumulado en cada turno hace que el bot
        # suene a formulario leyendo su propio estado en voz alta.
        recien: list[str] = []
        if datos.huellitas:
            nuevo["huellitas"] = datos.huellitas
            recien.append("huellitas")
            # Un anillo de una huellita lleva UNA pareja de colores. Si ya
            # había más apuntadas (porque los colores llegaron antes que la
            # cantidad), sobran y se van. Fabricar tres patitas en el anillo
            # de una es rehacerlo entero.
            if len(nuevo.get("colores", [])) > datos.huellitas:
                nuevo["colores"] = nuevo["colores"][: datos.huellitas]
        if datos.sku:
            nuevo["sku"] = datos.sku
        if datos.talla is not None:
            nuevo["talla"] = datos.talla
            recien.append("talla")
            # Talla sacada de una MEDIDA: se usa, y se marca para que alguien
            # la confirme antes de fundir. Las dos cosas a la vez — esa es
            # toda la política con lo que no escribimos nosotros.
            #
            # De dónde salió la medida cambia la nota que lee Lía, y la nota
            # es lo único que tiene para decidir. Decirle «de la foto de la
            # clienta» cuando no hubo foto la manda a buscar una imagen que no
            # existe.
            if datos.diametro_mm is not None:
                nuevo["diametro_mm"] = datos.diametro_mm
                de_una_foto = bool(i.foto) if i is not None else False
                if not de_una_foto:
                    nuevo["talla_revisar"] = True
                    nuevo["talla_motivo"] = (
                        f"la clienta ESCRIBIÓ la medida ({datos.diametro_mm:g} mm): "
                        f"confirmar con la foto del anillo sobre la regla"
                    )
                else:
                    nuevo["talla_revisar"] = not datos.foto_clara
                    nuevo["talla_motivo"] = (
                        "medida tomada de la foto de la clienta"
                        if datos.foto_clara
                        else "la foto no se leyó con seguridad: confirmar la talla"
                    )
                # El eco se lo cuenta a la clienta, así que tiene que decir la
                # verdad: «la saqué de tu foto» cuando ella la ESCRIBIÓ la deja
                # preguntándose qué foto mandó.
                recien.append("talla_de_foto" if de_una_foto else "talla_de_medida")
        # ── COLORES, INCLUSO A MEDIAS ─────────────────────────────────────
        #
        # Una pareja de colores casi nunca llega entera. «Morado y talla 5»,
        # «dedos morados», «morado» a secas: antes las tres se tiraban por no
        # estar completas, y el bot repetía la misma pregunta palabra por
        # palabra hasta que la clienta se iba. Media respuesta es media
        # respuesta, no ruido: se guarda y se pregunta SOLO lo que falta.
        media = dict(nuevo.get("media_pareja") or {})
        suelto = nuevo.get("color_suelto")

        # VARIAS HUELLITAS EN UN MISMO MENSAJE.
        #
        # «Corazón lila dedos rojos y el tercero verde corazón azul dedos»
        # son dos patitas. Van todas de una vez, sin pasar por la lógica de
        # medias parejas: aquí no hay nada a medias, están enteras.
        #
        # OJO CON SALIR DE AQUÍ ANTES DE TIEMPO. Esta rama terminaba con un
        # `return`, y con él se perdía todo lo que viene después: los NOMBRES
        # DEL GRABADO, la ciudad y los datos de envío. Un mensaje real de una
        # clienta —«quiero el de dos huellitas, 1 huella morado…, 2 huella
        # verde…, dentro grabado los nombres Lulu & Roberta»— entraba con los
        # dos colores y los dos nombres, y los nombres desaparecían sin que
        # nadie se enterara. Eso es lo que se graba en plata.
        if datos.parejas:
            esperadas = int(nuevo.get("huellitas") or 0)
            colores = list(nuevo.get("colores", []))
            for corazon, dedos in datos.parejas:
                par = {"corazon": corazon.value, "dedos": dedos.value}
                if esperadas and len(colores) >= esperadas:
                    colores[-1] = par  # ya están todas: esto corrige la última
                    if "correccion" not in recien:
                        recien.append("correccion")
                else:
                    colores.append(par)
            nuevo["colores"] = colores
            nuevo.pop("media_pareja", None)
            nuevo.pop("color_suelto", None)
            recien.append("colores")
            nuevo["_cuantas_colores"] = len(datos.parejas)
        else:
            if datos.color_corazon:
                media["corazon"] = datos.color_corazon.value
            if datos.color_dedos:
                media["dedos"] = datos.color_dedos.value

            # Un color sin parte («morado»): queda esperando a que diga cuál es.
            if datos.colores_sueltos and not (datos.color_corazon or datos.color_dedos):
                suelto = datos.colores_sueltos[0].value

            # …y la parte sin color («para el corazón») cierra el que esperaba.
            if datos.parte and suelto:
                media["corazon" if datos.parte == "CORAZON" else "dedos"] = suelto
                suelto = None

            # UN COLOR A SECAS, CON LA PAREJA A MEDIAS, ES LA PARTE QUE FALTA.
            #
            # Con media pareja puesta solo se le puede haber preguntado una
            # cosa: «anotado negro en el corazón, ¿y de qué color los
            # deditos?». Si contesta «rosado», eso es el color de los deditos y
            # no un color sin dueño. Antes se aparcaba como suelto, y el turno
            # siguiente salía con la MISMA pregunta palabra por palabra — en
            # una conversación real cuatro veces seguidas, hasta que se escaló
            # a una persona por una respuesta que estaba perfectamente clara.
            if suelto and len(media) == 1:
                media["dedos" if "corazon" in media else "corazon"] = suelto
                suelto = None

            if "corazon" in media and "dedos" in media:
                # Se acumulan: un anillo de tres huellitas lleva tres pares, y
                # cada mensaje trae uno. PERO NUNCA MÁS DE LOS QUE TIENE.
                #
                # Pasada la última, un par nuevo no es una huellita más: es una
                # corrección de la última. Acumular sin techo grababa varias
                # patitas en el anillo de una sola — y eso no se corrige con un
                # mensaje, se corrige fundiendo el anillo otra vez.
                esperadas = int(nuevo.get("huellitas") or 0)
                colores = list(nuevo.get("colores", []))
                if esperadas and len(colores) >= esperadas:
                    colores[-1] = media
                    recien.append("correccion")
                else:
                    colores.append(media)
                nuevo["colores"] = colores
                nuevo.pop("media_pareja", None)
                nuevo.pop("color_suelto", None)
                recien.append("colores")
            else:
                if media:
                    nuevo["media_pareja"] = media
                if suelto:
                    nuevo["color_suelto"] = suelto
                else:
                    nuevo.pop("color_suelto", None)
                # MEDIA RESPUESTA TAMBIÉN ES AVANZAR.
                #
                # Media pareja no cerraba ninguna huellita, así que no dejaba
                # rastro en `_recien` — y `_recien` es lo que le dice al
                # guardián de repeticiones que la clienta SÍ está contestando.
                # Sin esto, una clienta que iba dando color, grabado, nombre y
                # ciudad mientras faltaba la cantidad de huellitas sumaba una
                # insistencia por turno hasta que el bot la despachó con «mejor
                # te paso con una personita» — y le contestó eso a todo lo
                # demás, incluida una pregunta nueva.
                #
                # La etiqueta es propia y no «colores»: el eco no la conoce, así
                # que no cambia ni una palabra de lo que sale. Lo único que hace
                # es contar como avance.
                if (media, suelto) != (
                    dict(proceso.datos.get("media_pareja") or {}),
                    proceso.datos.get("color_suelto"),
                ):
                    recien.append("color_a_medias")

        # Otros anillos pedidos en el mismo mensaje. Se apuntan y se atienden
        # de uno en uno, cuando este quede cerrado.
        if datos.huellitas_extra:
            nuevo["cola"] = list(datos.huellitas_extra)
        if datos.nombres:
            nuevo["grabados"] = datos.nombres
            recien.append("grabado")
        if datos.sin_grabado:
            nuevo["sin_grabado"] = True
            recien.append("grabado")
        if datos.talla_despues:
            nuevo["sin_talla"] = True
            recien.append("talla_despues")
        if datos.nombre_envio:
            nuevo["nombre_envio"] = datos.nombre_envio
            recien.append("nombre")
        if datos.ciudad:
            nuevo["ciudad"] = datos.ciudad
            recien.append("ciudad")
        if datos.direccion:
            nuevo["direccion"] = datos.direccion
            recien.append("direccion")

        nuevo["_recien"] = recien
        proceso = proceso.model_copy(update={"datos": nuevo})
        proceso = proceso.model_copy(update={"faltan": self._faltan(proceso)})
        return self._cerrar_si_esta_completo(proceso, ctx, anterior=anterior)

    def _campos_cambiados(self, proceso: Proceso, anterior: Proceso | None):
        """(campos que trae este turno, cuáles de ellos ya tenían valor)."""
        recien = proceso.datos.get("_recien") or []
        campos = {self.CAMPO_DE[r] for r in recien if r in self.CAMPO_DE}
        if anterior is None:
            return campos, set()
        claves = {"grabado": "grabados", "nombre": "nombre_envio"}
        sobrescribe = {
            c
            for c in campos
            if anterior.datos.get(claves.get(c, c)) not in (None, "", [], False)
        }
        return campos, sobrescribe

    # -- de compra a pedido -------------------------------------------------

    def _cerrar_si_esta_completo(
        self, proceso: Proceso, ctx, anterior: Proceso | None = None
    ):
        """En cuanto no falta nada, el pedido EXISTE. No cuando ella pague.

        Es el eslabón que faltaba. Mientras la compra vivía solo en el
        contexto, «ya pagué» no tenía a qué referirse y el bot contestaba «no
        te entendí» justo en el momento de cobrar.

        Si el pedido ya estaba creado y ella corrige un color, se actualiza:
        el pedido no se duplica nunca, y esa es la razón de `pedido_id`.

        ════════════════════════════════════════════════════════════════════
        LA TALLA NO FRENA LA VENTA
        ════════════════════════════════════════════════════════════════════
        Falta un dato y es SIEMPRE el mismo: la talla. Y no falta porque no
        quiera darla — falta porque está en la calle, sin regla, y vuelve a
        escribir a los tres días. O no vuelve.

        Ese es el sitio exacto donde se pierden más ventas de todo el flujo,
        y es una restricción falsa: el negocio cobra el abono ANTES de tener
        la talla, porque la fabricación tarda diez días y la medida se
        confirma por el camino. `Personalizacion` ya lo dice —todos sus
        campos son opcionales— y era solo esta puerta la que no dejaba pasar.

        Así que con los colores y el grabado puestos el pedido nace igual, y
        la talla queda apuntada como pendiente, para ella y para el panel.
        """
        # Un pedido que YA EXISTE recibe el cambio aunque le falte algo por
        # preguntar (un pedido creado desde el panel sin dirección, por
        # ejemplo): que falte la dirección no puede impedir apuntar la talla.
        existente = proceso.datos.get("pedido_id")
        if proceso.pendientes and not (
            existente
            and self._m.pedido(existente) is not None
            and (proceso.datos.get("_recien") or [])
        ):
            return proceso, ctx.guardar_proceso(proceso)

        personalizacion = self._personalizacion_de(proceso)
        pedido_id = proceso.datos.get("pedido_id")

        # EL PEDIDO AL QUE APUNTA PUEDE NO EXISTIR YA.
        #
        # ════════════════════════════════════════════════════════════════════
        # LAS DOS MEMORIAS SE PUEDEN DESINCRONIZAR
        # ════════════════════════════════════════════════════════════════════
        # El contexto conversacional vive en SQLite y los pedidos viven en el
        # repositorio, que es OTRA cosa. Con `REPOSITORY_BACKEND=memory` los
        # pedidos se van al reiniciar y el contexto NO: queda un proceso
        # apuntando con `pedido_id` a un pedido que ya no existe.
        #
        # Pasó de verdad, en una conversación por WhatsApp, justo después de
        # cambiar el backend de memory a sqlite. `guardar_personalizacion`
        # levantaba `ConflictoDeEstado` y se caía el turno entero.
        #
        # No es solo cosa de `memory`: un pedido borrado a mano, una base
        # restaurada o dos entornos compartiendo conversación dejan la misma
        # referencia colgando. Y una referencia colgando NO puede costar una
        # venta: se olvida y el pedido se vuelve a crear con lo que ella ya
        # eligió, que sigue entero en el proceso.
        if pedido_id and self._m.pedido(pedido_id) is None:
            log.warning(
                "el proceso apuntaba a un pedido que ya no existe (%s): "
                "se olvida la referencia y se crea de nuevo",
                pedido_id,
            )
            proceso = proceso.model_copy(
                update={
                    "datos": {
                        k: v
                        for k, v in proceso.datos.items()
                        if k not in ("pedido_id", "codigo")
                    },
                    "pedido_id": None,
                }
            )
            pedido_id = None

        if pedido_id:
            return self._cambiar_pedido_existente(
                pedido_id, proceso, anterior, personalizacion, ctx
            )

        pedido = self._m.crear_pedido(
            ctx.conversation_id,
            int(proceso.datos["huellitas"]),
            personalizacion,
            envio=self._envio_de(proceso),
        )
        if pedido is None:
            # No se pudo. El proceso sigue abierto: se le contesta con lo que
            # se sabe y una persona lo recoge. Nunca se pierde la compra.
            log.warning("compra completa sin pedido: %s", proceso.id)
            return proceso, ctx.guardar_proceso(proceso)

        datos = {**proceso.datos, "pedido_id": pedido.id, "codigo": pedido.codigo}
        proceso = proceso.model_copy(update={"datos": datos, "pedido_id": pedido.id})
        ctx = ctx.guardar_proceso(proceso).enfocar("PEDIDO", pedido.id)

        # Nació sin talla: queda un proceso abierto para pedirla, y una nota
        # para que nadie lo mande a fabricar sin ella.
        if proceso.datos.get("talla") is None:
            ctx = ctx.guardar_proceso(
                Proceso(
                    tipo=TipoProceso.DATOS_PEDIDO,
                    pedido_id=pedido.id,
                    faltan=["talla"],
                )
            ).anotar_revision(
                f"El pedido {pedido.codigo} NO tiene talla todavía: "
                f"pedírsela antes de fabricar."
            )

        # ¿Pidió más de un anillo en el mismo mensaje? Se abre el siguiente.
        #
        # De uno en uno, nunca los dos a la vez: con dos compras abiertas, un
        # «talla 8» suelto es ambiguo y habría que preguntar a cuál va — que
        # es justo la pregunta que a nadie le gusta contestar. La cola cuesta
        # una clave en un diccionario; un carrito cuesta el resto del sistema.
        cola = list(proceso.datos.get("cola") or [])
        if cola:
            siguiente = Proceso(
                tipo=TipoProceso.COMPRA,
                datos={"huellitas": cola[0], "cola": cola[1:], "_recien": []},
            )
            siguiente = siguiente.model_copy(update={"faltan": self._faltan(siguiente)})
            proceso = proceso.model_copy(
                update={"datos": {**proceso.datos, "cola": [], "siguiente": cola[0]}}
            )
            ctx = ctx.guardar_proceso(proceso).guardar_proceso(siguiente)
        return proceso, ctx

    def _cambiar_pedido_existente(
        self, pedido_id: str, proceso: Proceso, anterior, personalizacion, ctx
    ):
        """Un dato nuevo para un pedido que YA EXISTE. Aquí se valida, no antes.

        El modelo pudo entender perfectamente el cambio; eso no lo autoriza.
        Lo autoriza el ESTADO del pedido (`domain.cambios.permiso`):

          APLICAR            se escribe (aún no se fabrica nada)
          APLICAR_Y_REVISAR  se escribe y queda nota para Lía
          PEDIR_A_PERSONA    NO se escribe: se anota la petición y se escala
          NUNCA              pedido cerrado: no se toca

        Cuando no se aplica, el proceso vuelve a como estaba: la conversación no
        puede creer que el anillo es rosado si el pedido sigue siendo azul.
        """
        from app.domain.cambios import Permiso, permiso

        pedido = self._m.pedido(pedido_id)
        campos, sobrescribe = self._campos_cambiados(proceso, anterior)
        veredicto = (
            Permiso.APLICAR
            if pedido is None
            else permiso(pedido.estado, campos, sobrescribe=sobrescribe)
        )
        if veredicto in (Permiso.PEDIR_A_PERSONA, Permiso.NUNCA):
            log.warning(
                "cambio NO aplicado a %s (%s): %s",
                pedido.codigo,
                pedido.estado,
                ",".join(sorted(campos)),
            )
            ctx = ctx.anotar_revision(
                f"La clienta pide cambiar {', '.join(sorted(campos))} en el pedido "
                f"{pedido.codigo} ({ETIQUETA_CLIENTE[OrderState(pedido.estado)]}). "
                f"NO se aplicó: confirmar con ella."
            )
            intacto = (anterior or proceso).model_copy(
                update={
                    "datos": {
                        **(anterior or proceso).datos,
                        "_recien": [],
                        "_cambio_para_persona": pedido.codigo,
                        "_estado_pedido": ETIQUETA_CLIENTE[OrderState(pedido.estado)],
                    }
                }
            )
            return intacto, ctx.guardar_proceso(
                intacto.model_copy(
                    update={
                        "datos": {
                            k: v
                            for k, v in intacto.datos.items()
                            if k not in ("_cambio_para_persona", "_estado_pedido")
                        }
                    }
                )
            )

        self._m.actualizar_personalizacion(pedido_id, personalizacion)
        if campos & {"nombre", "ciudad", "direccion"}:
            self._m.actualizar_envio(pedido_id, self._envio_de(proceso))
        if veredicto is Permiso.APLICAR_Y_REVISAR and pedido is not None:
            ctx = ctx.anotar_revision(
                f"Cambio de {', '.join(sorted(campos))} aplicado al pedido "
                f"{pedido.codigo} "
                f"que ya está {ETIQUETA_CLIENTE[OrderState(pedido.estado)]}: revisarlo "
                f"antes de seguir fabricando."
            )
        return proceso, ctx.guardar_proceso(proceso)

    # -- el historial: solo lee ---------------------------------------------

    def _consultar_historial(self, d, i, ctx):
        """Un pedido del pasado, que la clienta señaló. SOLO LEE.

        Nada de lo que se encuentre aquí entra al contexto operativo: no se
        enfoca, no abre procesos y no puede recibir un pago ni un cambio. Se
        registra como una lista de tipo HISTORICO para que «el segundo» del
        mensaje siguiente se pueda resolver, y eso es todo.
        """
        from app.domain.historial import FiltroHistorico, buscar, fecha_corta

        filtro = (i.historial if i is not None else None) or FiltroHistorico()
        operativo = ctx.operativo
        pedidos = self._m.historial_de(ctx.conversation_id)
        resultado = buscar(
            pedidos,
            filtro,
            activos=operativo.ids_activos if operativo is not None else frozenset(),
            en_foco=ctx.foco_id,
        )

        if resultado.ambiguo and self._desempate is not None and not filtro.resumen:
            elegido = self._desempate(
                (i.ruta.motivo if i is not None else ""), resultado, filtro
            )
            if elegido is not None:
                resultado.candidatos = [elegido]
                resultado.ambiguo = False
                resultado.criterio += " desempate_modelo"

        ficha = Ficha()
        ficha.datos["criterio"] = resultado.criterio
        ficha.datos["candidatos"] = str(len(resultado.candidatos))
        if i is not None:
            i.ruta.candidatos = len(resultado.candidatos)

        if not resultado.candidatos:
            ficha.datos["historial"] = "ninguno"
            ficha.datos["total_pedidos"] = str(len(pedidos))
            return ficha, ctx

        if resultado.unico is not None:
            pedido = resultado.unico
            ficha.datos["historial"] = "uno"
            ficha.datos.update(self._ficha_de_pedido(pedido).datos)
            ficha.literales = self._ficha_de_pedido(pedido).literales
            ficha.datos["fecha"] = fecha_corta(pedido.created_at)
            despachado = self._m.cuando_se_movio(pedido.id, OrderState.DESPACHADO)
            entregado = self._m.cuando_se_movio(pedido.id, OrderState.ENTREGADO)
            if despachado:
                ficha.datos["despachado"] = fecha_corta(despachado)
            if entregado:
                ficha.datos["entregado"] = fecha_corta(entregado)
            ficha.datos["cerrado"] = (
                "si" if OrderState(pedido.estado) in TERMINALES_HISTORIAL else "no"
            )
            return ficha, ctx.mostrar([("HISTORICO", pedido.id, pedido.codigo)])

        ficha.datos["historial"] = "varios"
        items = []
        for n, pedido in enumerate(resultado.candidatos[:10], start=1):
            etiqueta = (
                f"*{pedido.codigo}* · {fecha_corta(pedido.created_at)} · "
                f"{ETIQUETA_CLIENTE[OrderState(pedido.estado)]}"
            )
            ficha.datos[f"pedido_{n}"] = etiqueta
            items.append(("HISTORICO", pedido.id, pedido.codigo))
        ficha.datos["cuantos"] = str(len(resultado.candidatos))
        return ficha, ctx.mostrar(items)

    @staticmethod
    def _huellitas_de(datos: dict) -> list[Huellita]:
        return [
            Huellita(corazon=ColorCircon(c["corazon"]), dedos=ColorCircon(c["dedos"]))
            for c in datos.get("colores", [])
        ]

    def _personalizacion_de(self, proceso: Proceso) -> Personalizacion:
        d = proceso.datos
        return Personalizacion(
            talla_revisar=bool(d.get("talla_revisar")),
            talla_motivo=d.get("talla_motivo", ""),
            talla=d.get("talla"),
            huellitas=self._huellitas_de(d),
            grabados=d.get("grabados", []),
            sin_grabado=bool(d.get("sin_grabado")),
        )

    #: Claves internas del proceso: llevan guion bajo delante para que nunca
    #: se confundan con datos del anillo.
    INTERNAS = (
        "_recien",
        "_cambio_para_persona",
        "_estado_pedido",
        "_cuantas_colores",
        "sin_talla",
        "media_pareja",
        "color_suelto",
        "cola",
        "siguiente",
        "pedido_id",
    )

    def _faltan(self, proceso: Proceso) -> list[str]:
        """Qué falta para poder fabricar. Lo calcula el dominio, no una lista.

        Aquí está la diferencia con el diseño anterior: no hay un orden de
        preguntas. Hay un conjunto de huecos, y se pregunta el que quede.
        """
        cuantas = int(proceso.datos.get("huellitas") or 0)
        if not cuantas:
            return ["huellitas"]
        # El anillo entero y su nombre. Los datos de envío NO: se piden al
        # final, con las fotos del anillo terminado (Camilo, 20/09). Pedirlos
        # aquí es un formulario a alguien que todavía no ha comprado.
        return [
            *self._personalizacion_de(proceso).falta(cuantas),
            *self._envio_de(proceso).falta_para_tomar_el_pedido(),
        ]

    @staticmethod
    def _envio_de(proceso: Proceso) -> DatosDeEnvio:
        d = proceso.datos
        return DatosDeEnvio(
            nombre=d.get("nombre_envio", ""),
            ciudad=d.get("ciudad", ""),
            direccion=d.get("direccion", ""),
            telefono=d.get("telefono", ""),
        )

    def _ficha_de_proceso(self, proceso: Proceso, *, eco: bool = True) -> Ficha:
        """Los hechos de una compra a medias.

        `eco=False` cuando el turno NO trajo un dato nuevo. Sin eso, volver a
        preguntar arrastraba el «¡Perfecto! Anoté: …» del mensaje anterior y
        el bot parecía estar celebrando algo que ella no acababa de decir.
        """
        ficha = Ficha()
        d = proceso.datos
        ficha.datos["falta"] = ", ".join(proceso.pendientes)
        if eco and (recien := d.get("_recien")):
            ficha.datos["recien"] = ", ".join(recien)
            ficha.datos["cuantas_colores"] = str(d.get("_cuantas_colores") or 1)
        if cuantas := d.get("huellitas"):
            ficha.datos["huellitas"] = str(cuantas)
            producto = self._m.por_huellitas(int(cuantas))
            if producto is not None:
                cot = cotizar(
                    {producto.sku: producto},
                    [(producto.sku, 1)],
                    envio_contraentrega_cop=self._m.envio_a(d.get("ciudad")),
                )
                s = cot.slots()
                ficha.montos += [
                    formatear_cop(s["total"]),
                    formatear_cop(s["anticipo"]),
                    formatear_cop(s["saldo"]),
                    formatear_cop(s["envio_contraentrega"]),
                ]
                ficha.datos.update(
                    total=formatear_cop(s["total"]),
                    abono=formatear_cop(s["anticipo"]),
                    saldo=formatear_cop(s["saldo"]),
                    envio=formatear_cop(s["envio_contraentrega"]),
                    dias=str(s["dias"]),
                    dias_max=str(s["dias_max"]),
                    producto=producto.nombre,
                )
        if d.get("codigo"):
            ficha.datos["codigo"] = d["codigo"]
        if d.get("sin_talla") and d.get("talla") is None:
            ficha.datos["talla_pendiente"] = "si"
        if siguiente := d.get("siguiente"):
            ficha.datos["siguiente"] = str(siguiente)
        if codigo := d.get("_cambio_para_persona"):
            ficha.datos["cambio_para_persona"] = codigo
            ficha.datos["estado_pedido"] = d.get("_estado_pedido", "")
        # Lo que quedó a medias. Es lo que convierte «¿de qué color el corazón
        # y de qué color los deditos?» —otra vez, igualita— en «vi morado, ¿es
        # para el corazón o para los deditos?».
        if suelto := d.get("color_suelto"):
            from app.domain.personalizacion import NOMBRE_COLOR

            ficha.datos["color_suelto"] = NOMBRE_COLOR[ColorCircon(suelto)]
        if media := d.get("media_pareja"):
            from app.domain.personalizacion import NOMBRE_COLOR

            parte, valor = next(iter(media.items()))
            # Con artículo: «en el corazón», «los deditos». Sin él salía
            # «anotado morado en el deditos», que se lee como una máquina.
            ficha.datos["media_parte"] = (
                "el *corazón*" if parte == "corazon" else "los *deditos*"
            )
            ficha.datos["media_falta"] = (
                "los *deditos*" if parte == "corazon" else "el *corazón*"
            )
            ficha.datos["media_color"] = NOMBRE_COLOR[ColorCircon(valor)]
        if d.get("talla") is not None:
            ficha.datos["talla"] = f"{float(d['talla']):g}"
        if d.get("colores"):
            ficha.datos["colores_puestos"] = str(len(d["colores"]))
            # SU anillo, dibujado. En cuanto hay una huellita entera ya se
            # puede enseñar: no hay que esperar a tenerlas las tres, porque
            # es justo mientras escoge cuando le sirve verlo.
            if vista := self._m.previsualizar(self._huellitas_de(d)):
                ficha.datos["vista"] = vista

            from app.domain.personalizacion import NOMBRE_COLOR

            ficha.literales.append(
                " · ".join(
                    f"corazón {NOMBRE_COLOR[ColorCircon(c['corazon'])]} / "
                    f"dedos {NOMBRE_COLOR[ColorCircon(c['dedos'])]}"
                    for c in d["colores"]
                )
            )
        if d.get("grabados"):
            ficha.literales.append(", ".join(d["grabados"]))
        # A dónde va, para que lo pueda revisar antes de pagar. Una dirección
        # mal apuntada se descubre cuando el anillo vuelve.
        if destino := self._envio_de(proceso).describir():
            ficha.datos["envio_a"] = destino
        return ficha

    def _pedir_lo_que_falta(self, d, i, ctx):
        abiertos = ctx.abiertos(TipoProceso.COMPRA)
        if not abiertos:
            return Ficha(), ctx
        proceso, ctx = self._cerrar_si_esta_completo(abiertos[0], ctx)
        return self._ficha_de_proceso(proceso, eco=False), ctx

    def _retomar_proceso(self, d, i, ctx):
        abiertos = ctx.abiertos(TipoProceso.COMPRA)
        if not abiertos:
            return Ficha(), ctx
        # Tocarlo lo pone primero en la cola: «sigamos con el anillo» hace que
        # el siguiente dato suelto vaya a este y no a otro.
        proceso = abiertos[0].con()
        return self._ficha_de_proceso(proceso, eco=False), ctx.guardar_proceso(proceso)

    def _resumir_y_cobrar_abono(self, d, i, ctx):
        """«Listo, lo quiero». Si ya no falta nada, aquí nace el pedido.

        Se pasa por el mismo sitio que al anotar un dato —y no por otro
        camino— para que exista UNA sola forma de que un pedido nazca. Dos
        caminos hacia la misma escritura son dos sitios donde arreglar el
        próximo fallo, y solo se arregla uno.
        """
        abiertos = ctx.abiertos(TipoProceso.COMPRA)
        if not abiertos:
            return Ficha(), ctx
        proceso, ctx = self._cerrar_si_esta_completo(abiertos[0], ctx)
        # Sin eco: confirmar no es traer un dato nuevo, y repetirle «anoté
        # talla 8» cuando lo que hizo fue decir «confirmo» suena a que el bot
        # se está leyendo a sí mismo en voz alta.
        return self._ficha_de_proceso(proceso, eco=False), ctx

    # -- dinero: NADA de esto confirma un pago ------------------------------

    def _registrar_pago_reportado(self, d, i, ctx):
        """Que lo diga no es que haya pasado.

        Se abre un proceso para que quede constancia, se le pide el
        comprobante, y el pedido pasa a REVISIÓN — que no es pagado. Desde
        revisión no se puede producir ni despachar: la tabla de transiciones
        no lo permite. Confirmar un pago porque la clienta lo dijo sería la
        forma más cara posible de confiar; no enterar a Lía de que alguien
        dice haber pagado sería la más silenciosa de perder una venta.
        """
        pedido = self._m.marcar_pago_por_revisar(d.objetivo_id)
        proceso = Proceso(
            tipo=TipoProceso.PAGO_REPORTADO,
            pedido_id=d.objetivo_id,
            faltan=["comprobante"],
        )
        ctx = ctx.guardar_proceso(proceso)
        if pedido is not None:
            ctx = ctx.enfocar("PEDIDO", pedido.id)
            return self._ficha_de_pedido(pedido), ctx
        return Ficha(), ctx

    def _pedir_comprobante(self, d, i, ctx):
        return Ficha(), ctx

    def _recibir_comprobante(self, d, i, ctx):
        """Llegó la foto de la transferencia. Se acusa recibo y se deja lista.

        Ni la mira el bot para decidir: una captura de pantalla se edita en
        treinta segundos. Lo que hace esto es sacar a la clienta del limbo de
        «¿lo habrán recibido?» —que es donde se enfrían las ventas— y dejarle
        el trabajo hecho a quien verifica: el pedido queda EN REVISIÓN y la
        nota con lo que se leyó ya está en el panel.
        """
        pedido = self._m.marcar_pago_por_revisar(d.objetivo_id)
        proceso = Proceso(
            tipo=TipoProceso.PAGO_REPORTADO,
            pedido_id=d.objetivo_id,
            datos={"comprobante": True},
        )
        ctx = ctx.guardar_proceso(proceso)
        ficha = Ficha() if pedido is None else self._ficha_de_pedido(pedido)
        if pedido is not None:
            ctx = ctx.enfocar("PEDIDO", pedido.id)
            # De qué pago es el comprobante. Decirle «pasamos tu pedido a
            # producción» cuando lo que acaba de pagar es el saldo de un
            # anillo YA HECHO la deja pensando que empieza otra vez.
            ficha.datos["momento"] = (
                "saldo" if OrderState(pedido.estado) in YA_SE_FABRICO else "abono"
            )
        if i is not None and i.datos.monto_visto_cop:
            ficha.datos["monto_visto"] = formatear_cop(i.datos.monto_visto_cop)
        return ficha, ctx

    # -- deshacer -----------------------------------------------------------

    def _pedir_cancelacion(self, d, i, ctx):
        """Cancelar NO lo hace el bot. Se avisa a una persona.

        Un pedido cancelado por error es un anillo de plata ya fundido. Que lo
        decida alguien cuesta un minuto; equivocarse cuesta $200.000.
        """
        pedido = self._m.pedido(d.objetivo_id) if d.objetivo_id else None
        if pedido is None:
            return Ficha(), ctx
        return self._ficha_de_pedido(pedido), ctx.enfocar("PEDIDO", pedido.id)

    def _quitar_del_pedido(self, d, i, ctx):
        abiertos = ctx.abiertos(TipoProceso.COMPRA)
        if not abiertos:
            return Ficha(), ctx
        return self._ficha_de_proceso(abiertos[0]), ctx
