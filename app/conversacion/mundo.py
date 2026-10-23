"""Tramos 1 y 7: lo que el pipeline sabe del negocio, y cómo lo guarda.

Es la única pieza del gestor que toca repositorios. Existe para que el
pipeline no tenga que conocer siete puertos distintos, y para que los tests
puedan sustituirlo entero por un doble de veinte líneas.

UNA DECISIÓN QUE IMPORTA: `pedidos_de(cliente)` devuelve TODOS los abiertos,
no «el activo». El diseño anterior devolvía uno solo, y por eso una clienta
que volvía a comprar pisaba su pedido anterior. No era una funcionalidad
pendiente: era un fallo, y es el caso más común de todos, porque una clienta
contenta vuelve.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.domain.anuncios import Referido, anuncio_del_pedido, con_toque
from app.domain.contexto import ContextoConversacional, Mencion
from app.domain.envio import DatosDeEnvio
from app.domain.faq import ENVIO_NACIONAL_COP
from app.domain.models import Channel, Customer, Order, conversation_id, new_id
from app.domain.order_state import ETIQUETA_CLIENTE, TERMINALES, OrderState
from app.domain.personalizacion import Personalizacion
from app.domain.pricing import cotizar
from app.domain.services import aplicar_cotizacion, siguiente_codigo, transicionar

log = logging.getLogger("ventabot.mundo")

#: Por dónde pasa un pedido recién armado hasta quedar esperando el abono.
#: Se escribe la ruta entera y no el destino porque la máquina de estados no
#: permite atajos: cada paso deja su evento de auditoría, y ese rastro es lo
#: único que sirve el día que alguien pregunte «¿y este pedido de dónde salió?».
CAMINO_HASTA_EL_ABONO = (
    OrderState.COTIZADO,
    OrderState.CONFIRMADO,
    OrderState.ESPERANDO_ANTICIPO,
)


def etiquetar(pedido: Order) -> str:
    """Cómo se nombra un pedido en una lista y al resolver «el rosado».

    El texto es el mismo que ve la clienta, a propósito: si ella lee «Anillo
    huellita — en el taller», tiene que poder decir «el del taller» y que se
    resuelva. Dos textos distintos, uno para mostrar y otro para buscar, se
    desincronizan el primer día.
    """
    nombre = pedido.items[0].nombre if pedido.items else "Pedido"
    if len(pedido.items) > 1:
        nombre = (
            f"{len(pedido.items)} anillos ({', '.join(i.nombre for i in pedido.items)})"
        )
    estado = ETIQUETA_CLIENTE.get(OrderState(pedido.estado), pedido.estado)
    p = pedido.items[0].personalizacion if pedido.items else None
    detalle = ""
    if p and p.huellitas:
        colores = {h.corazon for h in p.huellitas}
        if len(colores) == 1:
            from app.domain.personalizacion import NOMBRE_COLOR

            detalle = f" {NOMBRE_COLOR[next(iter(colores))]}"
    return f"{nombre}{detalle} — {estado}"


class Mundo:
    def __init__(
        self, orders, customers, products, contexto_repo, render=None, fletes=None
    ) -> None:
        self._orders = orders
        self._customers = customers
        self._products = products
        self._ctx = contexto_repo
        #: Quien dibuja las previsualizaciones. Puede no existir: sin él la
        #: conversación es idéntica, solo que sin fotos de cómo va a quedar.
        self._render = render
        #: La tabla de envíos por ciudad. Sin ella se cobra el flete nacional
        #: por defecto, que es lo que hacía hasta ahora.
        self._fletes = fletes

    # -- contexto -----------------------------------------------------------

    def contexto(self, conv_id: str) -> ContextoConversacional:
        return self._ctx.cargar(conv_id)

    def guardar_contexto(self, ctx: ContextoConversacional) -> None:
        self._ctx.guardar(ctx)

    # -- atención humana ----------------------------------------------------

    def la_atiende_una_persona(self, conv_id: str) -> bool:
        """¿Hay alguien contestando a mano en esta conversación ahora?"""
        from app.domain.atencion import en_pausa

        return en_pausa(self.contexto(conv_id).humano_hasta)

    def pausar_por_humano(self, conv_id: str, horas: float | None = None) -> None:
        """Alguien escribió a mano: el bot se calla un rato en esta charla."""
        from app.domain.atencion import HORAS_DE_PAUSA, pausar

        ctx = self.contexto(conv_id)
        self.guardar_contexto(
            ctx.model_copy(update={"humano_hasta": pausar(horas or HORAS_DE_PAUSA)})
        )

    def devolver_al_bot(self, conv_id: str) -> None:
        """Quien atendía suelta la conversación: el bot vuelve a contestar."""
        self.ya_la_atendieron(conv_id)
        ctx = self.contexto(conv_id)
        self.guardar_contexto(ctx.model_copy(update={"humano_hasta": None}))

    def ya_la_atendieron(self, conv_id: str) -> None:
        """«Ya lo atendí» (resolver, devolver): se va la alerta de «necesita
        persona». NO cambia quién la lleva (09/10: resolver ≠ devolver)."""
        ctx = self.contexto(conv_id)
        self.guardar_contexto(
            ctx.model_copy(
                update={
                    "necesita_persona": False,
                    # La próxima vez que la necesiten, otra nota.
                    "crm_hecho": [h for h in ctx.crm_hecho if h != "persona"],
                }
            )
        )

    def anotar_mensaje_de_humano(self, conv_id: str, texto: str) -> None:
        """Lo que escribió la persona entra en la charla que lee la asesora.

        Sin esto, cuando el bot vuelva no sabría qué se le prometió a la
        clienta mientras tanto, y podría contradecirlo.
        """
        ctx = self.contexto(conv_id)
        charla = [*ctx.charla, {"de": "lia", "texto": (texto or "")[:700]}]
        self.guardar_contexto(ctx.model_copy(update={"charla": charla[-30:]}))

    def anotar_nota_interna(self, conv_id: str, nota: dict) -> None:
        """Una nota interna de Lía (`app.domain.notas_internas`). APARTE de la
        charla: la asesora la lee como contexto, no como algo que dijo nadie."""
        from app.domain.notas_internas import GUARDADAS

        if not (nota.get("texto") or "").strip():
            return
        ctx = self.contexto(conv_id)
        notas = [*ctx.notas_internas, nota][-GUARDADAS:]
        self.guardar_contexto(ctx.model_copy(update={"notas_internas": notas}))

    def fijar_talla_de_lia(
        self, conv_id: str, talla: float, motivo: str, anillo: int | None = None
    ) -> None:
        """Lía confirmó o corrigió la talla: desde ahora ESA es la talla.

        Se pone en la memoria de la conversación igual que en el pedido. Si
        solo cambiara el pedido, el turno siguiente podría devolverle la
        estimación vieja desde el borrador. `anillo` (desde 0) en una compra de
        varios; None = el que esperaba la talla (`Borrador.fijar_talla`).
        """
        from app.domain.asesora import Borrador

        ctx = self.contexto(conv_id)
        b = Borrador.model_validate(ctx.borrador) if ctx.borrador else Borrador()
        # Si Lía confirma una talla, es que la regla de Lía está puesta: así
        # se encuentra el anillo que la esperaba.
        exige, b.talla_exige_lia = b.talla_exige_lia, True
        b.fijar_talla(anillo, talla, motivo)
        b.talla_exige_lia = exige
        self.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )

    def anotar_aviso_del_sistema(self, conv_id: str, texto: str) -> None:
        """Un aviso de estado (entró al taller, está listo, va en camino) que le
        llegó a la clienta: también es parte de la conversación que lee el bot."""
        if not (texto or "").strip():
            return
        ctx = self.contexto(conv_id)
        linea = {"de": "lia", "texto": "[aviso automático] " + texto[:600]}
        charla = [*ctx.charla, linea]
        self.guardar_contexto(ctx.model_copy(update={"charla": charla[-30:]}))

    # -- clienta ------------------------------------------------------------

    def cliente_de(self, conv_id: str) -> Customer | None:
        canal, _, user_id = conv_id.partition(":")
        equivalente = {"wa": Channel.WHATSAPP, "ig": Channel.INSTAGRAM}.get(canal)
        if equivalente is None:
            return None
        return self._customers.get_by_channel_user(equivalente.value, user_id)

    def asegurar_cliente(self, conv_id: str) -> Customer:
        """La devuelve, creándola si es su primer mensaje."""
        existente = self.cliente_de(conv_id)
        if existente is not None:
            return existente
        canal, _, user_id = conv_id.partition(":")
        equivalente = {"wa": Channel.WHATSAPP, "ig": Channel.INSTAGRAM}[canal]
        return self._customers.upsert(
            Customer(channel=equivalente, channel_user_id=user_id)
        )

    def anotar_anuncio(self, conv_id: str, toque: Referido) -> Customer | None:
        """Ella llegó tocando un anuncio: primer y último toque (ADR 0028)."""
        cliente = self.asegurar_cliente(conv_id)
        primero, ultimo = con_toque(cliente.primer_anuncio, toque)
        return self._customers.upsert(
            cliente.model_copy(
                update={"primer_anuncio": primero, "ultimo_anuncio": ultimo}
            )
        )

    # -- pedidos ------------------------------------------------------------

    def pedidos_de(self, conv_id: str) -> list[Order]:
        """TODOS los pedidos abiertos, del más reciente al más viejo."""
        cliente = self.cliente_de(conv_id)
        if cliente is None:
            return []
        if hasattr(self._orders, "de_cliente"):
            abiertos = self._orders.de_cliente(cliente.id, solo_activos=True)
        else:  # un repositorio que todavía no sabe filtrar por clienta
            abiertos = [o for o in self._orders.abiertos() if o.customer_id == cliente.id]
        abiertos = [o for o in abiertos if OrderState(o.estado) not in TERMINALES]
        return sorted(abiertos, key=lambda o: o.created_at, reverse=True)

    # -- el CONTEXT RESOLVER --------------------------------------------------

    def resolver_contexto(self, ctx: ContextoConversacional) -> ContextoConversacional:
        """Tramo 1: el contexto del turno, reconciliado con la base de datos.

        Separa las cuatro memorias y deja cada una en su sitio:

          · RECIENTE    los últimos mensajes. NO van aquí: solo se leen cuando
                        se escala al modelo potente, y con ventana de tiempo.
          · OPERATIVO   pedidos ACTIVOS + compra en curso. Se construye aquí,
                        desde la base de datos, en cada turno.
          · MEMORIA     lo estable de la clienta (su ciudad). Vive en el
                        contexto y no depende de ningún pedido.
          · HISTORIAL   los pedidos cerrados. Aquí solo se CUENTAN; se leen de
                        verdad únicamente con `historial_de`, a petición.

        Todo lo que el contexto guardado tenga apuntando a un pedido cerrado
        (un proceso de compra, un pago reportado, el foco, una lista) sale del
        contexto normal. Nunca falla: si la base de datos no responde, se sigue
        con el contexto como estaba, que es lo que pasaba antes.
        """
        from app.domain.operativo import construir, ids_referenciados, sanear

        try:
            activos = self.pedidos_de(ctx.conversation_id)
            ids_activos = {o.id for o in activos}
            cerrados: set[str] = set()
            for pedido_id in ids_referenciados(ctx) - ids_activos:
                pedido = self._orders.get(pedido_id)
                if pedido is not None and OrderState(pedido.estado) in TERMINALES:
                    cerrados.add(pedido_id)
            saneado = sanear(ctx, cerrados=cerrados, activos=ids_activos)
            cliente = self.cliente_de(ctx.conversation_id)
            n_cerrados = (
                self._orders.contar_cerrados(cliente.id)
                if cliente is not None and hasattr(self._orders, "contar_cerrados")
                else 0
            )
        except Exception as exc:  # la base de datos no puede costar el turno
            log.warning("no se pudo resolver el contexto operativo (%s)", exc)
            return ctx.limpiar()

        if saneado.archivados:
            log.info("  contexto saneado: %s", "; ".join(saneado.archivados))
        nuevo = saneado.contexto
        return nuevo.model_copy(
            update={
                "operativo": construir(
                    nuevo, activos, cerrados=n_cerrados, archivados=saneado.archivados
                )
            }
        )

    def historial_de(self, conv_id: str, limite: int = 50) -> list[Order]:
        """TODOS los pedidos de la clienta, cerrados incluidos. Solo a petición."""
        cliente = self.cliente_de(conv_id)
        if cliente is None:
            return []
        if hasattr(self._orders, "de_cliente"):
            return self._orders.de_cliente(cliente.id, limite=limite)
        return []

    def cuando_se_movio(self, pedido_id: str, estado: OrderState) -> datetime | None:
        """Cuándo llegó el pedido a ese estado, según la auditoría. O None."""
        eventos = getattr(self._orders, "eventos", None)
        if eventos is None:
            return None
        try:
            fechas = [
                e.created_at for e in eventos(pedido_id) if e.estado_nuevo == estado.value
            ]
        except Exception:
            return None
        return max(fechas) if fechas else None

    def pedido(self, pedido_id: str) -> Order | None:
        return self._orders.get(pedido_id)

    def menciones_de_pedidos(self, conv_id: str) -> list[Mencion]:
        return [
            Mencion(
                posicion=i,
                tipo="PEDIDO",
                id=o.id,
                etiqueta=etiquetar(o),
                codigo=o.codigo,
            )
            for i, o in enumerate(self.pedidos_de(conv_id), start=1)
        ]

    def menciones_con_saldo(self, conv_id: str) -> list[Mencion]:
        """Los pedidos que deben plata.

        Es lo que hace que «ya pagué» no sea ambiguo cuando tiene tres pedidos
        pero solo uno debe. Restringir el universo a lo que la frase puede
        significar quita casi todas las preguntas innecesarias, que es la
        mitad de parecer natural.
        """
        from app.domain.operativo import pendiente_de_pago

        salida = []
        for i, o in enumerate(self.pedidos_de(conv_id), start=1):
            # Lo que falta pagar sale del ESTADO confirmado por una persona, no
            # de un campo de monto que el panel no rellena (ver
            # `operativo.pendiente_de_pago`).
            if pendiente_de_pago(o) > 0:
                salida.append(
                    Mencion(
                        posicion=i,
                        tipo="PEDIDO",
                        id=o.id,
                        etiqueta=etiquetar(o),
                        codigo=o.codigo,
                    )
                )
        return salida

    # -- de una compra a medias a un pedido de verdad -----------------------

    def crear_pedido(
        self,
        conv_id: str,
        huellitas: int,
        personalizacion: Personalizacion,
        envio: DatosDeEnvio | None = None,
    ) -> Order | None:
        """Un pedido de UN anillo. Ver `crear_pedido_de_anillos`."""
        return self.crear_pedido_de_anillos(
            conv_id, [(huellitas, personalizacion)], envio=envio
        )

    def crear_pedido_de_anillos(
        self,
        conv_id: str,
        anillos: list[tuple[int, Personalizacion]],
        envio: DatosDeEnvio | None = None,
    ) -> Order | None:
        """Convierte una compra terminada en un PEDIDO. Aquí nace el negocio.

        Una línea por anillo, cada una con SU personalización (02/10): dos
        anillos son un pedido, con un abono y un saldo, como los cobra Lía.

        ════════════════════════════════════════════════════════════════════
        POR QUÉ ESTO FALTABA Y SE NOTABA TANTO
        ════════════════════════════════════════════════════════════════════
        El gestor nuevo armaba la compra en un `Proceso` y le mostraba el
        resumen con el total. Precioso. Pero el proceso vivía solo en el
        contexto de la conversación: no existía ningún `Order`.

        Consecuencia: cuando la clienta decía «ya pagué», la validación
        buscaba un pedido al que referirse, no encontraba ninguno, y el bot
        contestaba «no te entendí». La ruta del dinero estaba cortada justo
        en el sitio donde entra el dinero.

        Devuelve None si algo no cuadra (el producto no existe, la cotización
        falla). None es una respuesta legítima: el bot dirá lo que sabe y
        pedirá una persona, que es mejor que un pedido a medio crear.
        """
        cliente = self.cliente_de(conv_id)
        productos = [self.producto_de(h, p.pieza) for h, p in anillos]
        if cliente is None or not anillos or None in productos:
            log.warning("no se pudo crear el pedido: cliente o producto ausente")
            return None

        # El anillo de dos huellitas NO se manda a fabricar con una sola
        # pareja de colores apuntada, ni con tres. Es la última puerta antes
        # de que esto se convierta en plata fundida, y por eso se comprueba
        # aquí además de en `Personalizacion.falta()`: son dos capas porque
        # equivocarse cuesta el anillo, el envío y la clienta.
        # La talla puede faltar (se cobra el abono antes de tenerla); los
        # colores NO: sin ellos no hay nada que fundir.
        for huellitas, personalizacion in anillos:
            if len(personalizacion.huellitas) != huellitas:
                log.warning(
                    "no se crea el pedido: %s huellitas pedidas y %s parejas de "
                    "colores guardadas",
                    huellitas,
                    len(personalizacion.huellitas),
                )
                return None

        try:
            cot = cotizar(
                {p.sku: p for p in productos},
                [(p.sku, 1) for p in productos],
                envio_contraentrega_cop=self.envio_a(envio.ciudad if envio else None),
            )
        except (KeyError, ValueError) as exc:
            log.warning("no se pudo cotizar %s: %s", [p.sku for p in productos], exc)
            return None

        # El teléfono no se pregunta: está escribiendo por WhatsApp.
        destino = (envio or DatosDeEnvio()).model_copy(
            update={"telefono": cliente.channel_user_id}
        )
        pedido = Order(
            codigo=self._codigo_libre(),
            customer_id=cliente.id,
            estado=OrderState.BORRADOR.value,
            envio=destino,
        )
        # A qué anuncio se le cuenta esta venta. Se copia AHORA y no se
        # recalcula: si mañana toca otro anuncio, este pedido no se mueve.
        pedido.anuncio = anuncio_del_pedido(cliente.ultimo_anuncio, pedido.created_at)
        pedido = aplicar_cotizacion(pedido, cot)
        pedido = self._orders.create(pedido, idem_key=f"compra:{pedido.id}")

        for destino in CAMINO_HASTA_EL_ABONO:
            pedido = transicionar(
                self._orders,
                pedido,
                destino,
                actor="bot",
                motivo="la clienta terminó de armar su anillo",
                idem_key=f"alta:{pedido.id}:{destino.value}",
            )

        # La personalización va DESPUÉS del alta: si algo falla al guardarla,
        # el pedido existe igual y Lía puede completarlo desde el panel. Al
        # revés se perdería el pedido entero por un color.
        for indice, (_, personalizacion) in enumerate(anillos):
            self._orders.guardar_personalizacion(
                pedido.id, personalizacion, indice if len(anillos) > 1 else None
            )
        return self._orders.get(pedido.id) or pedido

    #: Desde dónde tiene sentido decir «esta clienta dice que pagó».
    #: Fuera de estos dos estados, o ya está cobrado o todavía no hay nada
    #: que cobrar, y mover el pedido sería ruido para Lía.
    ESPERANDO_PLATA = (OrderState.ESPERANDO_ANTICIPO, OrderState.ESPERANDO_SALDO)

    def marcar_pago_por_revisar(self, pedido_id: str) -> Order | None:
        """La clienta dice que pagó. El pedido pasa a REVISIÓN, no a pagado.

        ════════════════════════════════════════════════════════════════════
        ESTO NO CONFIRMA NADA
        ════════════════════════════════════════════════════════════════════
        `EN_REVISION_PAGO` existe justo para esto: hay un comprobante o una
        afirmación sin conciliar. Desde ahí NO se puede producir ni despachar
        —la tabla de transiciones no lo permite—, así que nadie funde plata
        por creerle a un mensaje.

        Lo que sí hace es sacarlo del limbo: sin esto, «ya pagué» solo dejaba
        un proceso dentro de la conversación, que Lía no ve por ningún lado.
        Un aviso que nadie mira es lo mismo que no avisar, y esa es la parte
        del circuito del dinero donde no puede haber silencio.
        """
        pedido = self._orders.get(pedido_id) if pedido_id else None
        if pedido is None or OrderState(pedido.estado) not in self.ESPERANDO_PLATA:
            return pedido
        try:
            return transicionar(
                self._orders,
                pedido,
                OrderState.EN_REVISION_PAGO,
                actor="bot",
                motivo="la clienta dice que pagó; falta verificar",
                idem_key=f"reporte:{pedido.id}:{pedido.estado}",
            )
        except Exception as exc:  # el pedido se movió por otro lado
            log.warning("no se pudo marcar en revisión %s: %s", pedido_id, exc)
            return pedido

    def actualizar_envio(self, pedido_id: str, envio: DatosDeEnvio) -> None:
        """La dirección, la ciudad o el nombre de un pedido que ya existe.

        Antes no existía: «cambio la dirección a …» se perdía aunque se
        entendiera, porque solo se guardaba la personalización. El teléfono se
        conserva: está escribiendo por WhatsApp desde él.
        """
        pedido = self._orders.get(pedido_id)
        if pedido is None:
            return
        destino = envio.model_copy(
            update={"telefono": pedido.envio.telefono or envio.telefono}
        )
        self._orders.guardar_pedido(pedido.model_copy(update={"envio": destino}))

    def actualizar_personalizacion(
        self, pedido_id: str, personalizacion: Personalizacion, indice: int | None = None
    ) -> None:
        """Cuando corrige un color después de que el pedido ya existe.

        `indice`: qué anillo, en un pedido de varios (None = el único)."""
        self._orders.guardar_personalizacion(pedido_id, personalizacion, indice)

    def _codigo_libre(self) -> str:
        """PED-2026-0417, comprobando que no exista ya.

        El consecutivo no puede salir de un contador en memoria: hay un solo
        proceso hoy y habrá varios mañana. Se sortea y se comprueba, que para
        diez mil códigos y cincuenta pedidos al mes no colisiona nunca — y si
        colisionara, se vuelve a sortear.
        """
        anio = datetime.now(UTC).year
        for _ in range(25):
            codigo = siguiente_codigo(anio, abs(hash(new_id())) % 10_000)
            if self._orders.get_by_code(codigo) is None:
                return codigo
        return siguiente_codigo(anio, abs(hash(new_id())) % 10_000)

    @property
    def fletes(self):
        """La tabla de envíos (para el panel). None si no hay."""
        return self._fletes

    def ciudades_conocidas(self) -> list[str]:
        """Las ciudades de la tabla de envíos: para reconocerlas en un mensaje."""
        try:
            if not self._fletes:
                return []
            return [getattr(f, "ciudad", f) for f in self._fletes.ciudades()]
        except Exception:  # pragma: no cover - una tabla rara no tumba el turno
            return []

    def envio_a(self, ciudad: str | None) -> int:
        """Lo que cuesta el flete a esa ciudad. Nunca falla.

        Si la ciudad no está en la tabla se cobra el nacional por defecto y
        una persona lo ajusta: un pedido no se puede caer porque la clienta
        viva en un pueblo que nadie tecleó todavía.
        """
        if self._fletes is None:
            return ENVIO_NACIONAL_COP
        try:
            # SIN CIUDAD manda la fila `(DEFECTO)` del CSV, no la constante.
            # Es el caso más frecuente —el envío se pregunta antes que la
            # dirección— y es justo el número que Camilo tiene que poder
            # cambiar con Excel. Caer aquí a la constante haría que ese
            # cambio no se notara en la mitad de las conversaciones.
            if not ciudad:
                return int(self._fletes.costo_por_defecto)
            return int(self._fletes.buscar(ciudad).costo_cop)
        except Exception as exc:  # pragma: no cover - defensa
            log.warning("no se pudo mirar el flete de %s (%s)", ciudad, exc)
            return ENVIO_NACIONAL_COP

    # -- enseñarle cómo va a quedar -----------------------------------------

    def previsualizar(self, huellitas: list) -> str | None:
        """El nombre lógico de la foto de SU anillo, o None si no se pudo.

        Nunca lanza. Enseñarle cómo queda es lo que convierte una decisión
        abstracta en un «¡ay, sí!», pero si el dibujo falla la conversación
        no puede enterarse.
        """
        if self._render is None or not huellitas:
            return None
        try:
            return self._render.previsualizar(list(huellitas))
        except Exception as exc:
            log.warning("no se pudo previsualizar (%s)", exc)
            return None

    def previsualizar_corazon(self, color) -> str | None:
        """La foto del corazón solo, de su color (el anillo de corazón, 17/10).
        Nunca lanza, igual que `previsualizar`."""
        dibujar = getattr(self._render, "previsualizar_corazon", None)
        if dibujar is None or color is None:
            return None
        try:
            return dibujar(color)
        except Exception as exc:
            log.warning("no se pudo previsualizar el corazón (%s)", exc)
            return None

    # -- catálogo -----------------------------------------------------------

    def productos(self):
        return self._products.list_active()

    def producto(self, sku: str):
        return next((p for p in self.productos() if p.sku == sku), None)

    def por_huellitas(self, cuantas: int):
        """El ANILLO de tantas huellitas (la cadena también tiene 1: no cuenta)."""
        return next(
            (
                p
                for p in self.productos()
                if p.huellitas == cuantas and p.categoria == "anillos"
            ),
            None,
        )

    def cadena(self):
        """La cadena con huellita (03/10), si está en el catálogo."""
        return next((p for p in self.productos() if p.categoria == "cadenas"), None)

    def corazon(self):
        """El anillo de corazón (17/10), si está en el catálogo."""
        return next((p for p in self.productos() if p.categoria == "corazones"), None)

    def producto_de(self, huellitas: int, pieza: str = "anillo"):
        if pieza == "cadena":
            return self.cadena()
        if pieza == "corazon":
            return self.corazon()
        return self.por_huellitas(huellitas)

    @staticmethod
    def conversacion_de(cliente: Customer) -> str:
        return conversation_id(cliente.channel, cliente.channel_user_id)
