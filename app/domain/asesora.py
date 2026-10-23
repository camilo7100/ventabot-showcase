"""La asesora: lo que el modelo PROPONE y lo que Python DEJA pasar.

════════════════════════════════════════════════════════════════════════════
POR QUÉ EXISTE (ADR 0014)
════════════════════════════════════════════════════════════════════════════
Se reprodujeron, frase por frase, las siete conversaciones reales de Lía contra
el gestor por etiquetas (`app.conversacion.pipeline`). Ninguna llegó al abono.
No por falta de reglas —hay miles de líneas— sino porque una clienta real no
contesta la pregunta que se le hizo: manda la talla cuando se le preguntan los
colores, el nombre de su gata cuando se le pregunta el grabado, y su propio
nombre cuando Lía se lo pide para el taller. Clasificar cada mensaje suelto en
una etiqueta pierde justo eso.

Aquí el modelo lee la conversación reciente y el BORRADOR del pedido y devuelve
una `Jugada`: qué cambia en el borrador, qué acciones pide y qué le escribiría
Lía. Lo que sigue siendo de Python, sin excepción:

  · los colores son el `Enum` de 14 del muestrario: el esquema no deja otro;
  · la talla tiene que existir en el mandril, y la medida escrita se marca;
  · el grabado no puede ser el nombre de la clienta ni pasar de 5 nombres;
  · los precios, las cuentas y el resumen los escribe Python, nunca el modelo;
  · el mensaje se vigila: sin montos inventados, sin «pago confirmado»;
  · un pago lo confirma una persona (ADR 0011), siempre.

Todo en este módulo es puro: se prueba sin red y en microsegundos.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from enum import Enum

from pydantic import BaseModel, Field, PrivateAttr

from app.domain.faq import DIRECCION_DE_CASA
from app.domain.personalizacion import (
    ANILLO,
    CADENA,
    CORAZON,
    EMOJI_COLOR,
    HUELLITAS_DE_LA_CADENA,
    NOMBRE_COLOR,
    PIEDRAS_DEL_CORAZON,
    ColorCircon,
    Huellita,
    Personalizacion,
    lados_de_la_cadena,
    texto_del_grabado,
    unir_grabados,
)
from app.domain.promociones import promete_una_promocion
from app.domain.tallas import DIAMETRO_MM, estimar, leer_talla, talla_texto

#: Nombres grabados en el aro, como máximo. Restricción física.
MAX_NOMBRES = 5
#: Un renglón de grabado más largo que esto se deja pasar, pero con nota para
#: Lía: rechazarlo perdería la venta y el tope real depende de la talla.
LARGO_A_REVISAR = 28
#: Mensajes de la conversación que se le muestran al modelo.
CHARLA_MAXIMA = 30
#: Problemas del vigilante que invalidan el mensaje ENTERO, no solo la frase:
#: lo que queda alrededor sigue hablando como si la mentira fuera verdad.
PROBLEMAS_GRAVES = (
    "llama al negocio por un nombre",
    "da el pedido por tomado",
    "dice que ya mandó las cuentas",
    "afirma un pago confirmado",
    "habla de pagar o del comprobante sin haberle mandado las cuentas",
    "dice que el anillo sigue en el taller",
    "dice que ya se despachó",
    "dice que el pedido entra al taller sin el abono",
    "dice «recibido» sin que haya llegado un comprobante",
    "junta el envío con el abono",
)
#: Un mensaje de WhatsApp de más de esto ya no es «como escribe Lía».
LARGO_MAXIMO_MENSAJE = 900


# ══════════════════════════════════════════════════════════════════════════
#  EL BORRADOR: el pedido tal como va quedando en la conversación
# ══════════════════════════════════════════════════════════════════════════


class HuellitaDelBorrador(BaseModel):
    corazon: ColorCircon | None = None
    dedos: ColorCircon | None = None
    #: Los cuatro deditos cuando no van iguales («negro-blanco-negro-blanco»).
    dedos_alternos: list[ColorCircon] = Field(default_factory=list)
    #: De quién es la patita («Gordo», «la del negrito»). Ayuda a no cruzarlas.
    mascota: str = ""

    @property
    def completa(self) -> bool:
        return self.corazon is not None and (
            self.dedos is not None or len(self.dedos_alternos) == 4
        )

    def describir(self) -> str:
        """Cómo va esta huellita, con el formato del resumen de Lía.

        El emoji va SOLO en el corazón: los deditos alternos ya llevan cuatro
        nombres y con cuatro emojis más no se leería nada.
        """
        corazon = (
            f"{EMOJI_COLOR[self.corazon]} {_bonito(self.corazon)}"
            if self.corazon
            else "por escoger"
        )
        if len(self.dedos_alternos) == 4:
            dedos = "-".join(_bonito(c) for c in self.dedos_alternos)
        else:
            dedos = _bonito(self.dedos) if self.dedos else "por escoger"
        if (
            self.dedos is not None
            and self.dedos == self.corazon
            and not self.dedos_alternos
        ):
            return f"{corazon} (toda la huellita)"
        return f"{corazon} / Dedos: {dedos}"


#: Lo que falta cuando la talla espera a Lía. El paréntesis es para el
#: modelo, que lee esta lista: eso NO se le pide a la clienta.
TALLA_DE_LIA = "que Lía confirme la talla (lo hace ella; NO se le pide a la clienta)"

#: Lo que falta cuando compra varios anillos y todavía no se empieza el
#: siguiente: «describir el anillo 2 de 3». Va DESPUÉS de lo del anillo actual.
ANILLO_SIGUIENTE = "describir el anillo"
#: Tope de anillos en una misma compra. Más ya es un pedido de mayorista: Lía.
MAX_ANILLOS = 5
#: Lo que es de UN anillo (no de la clienta ni del envío).
CAMPOS_DE_LA_TALLA = (
    "talla",
    "talla_revisar",
    "talla_motivo",
    "talla_rango",
    "talla_confirmada",
    "talla_fotos",
    "talla_escrita",
)
CAMPOS_DEL_ANILLO = (
    "pieza",
    "cantidad",
    "huellitas",
    "grabado",
    "sin_grabado",
    *CAMPOS_DE_LA_TALLA,
)


class AnilloListo(BaseModel):
    """Un anillo ya descrito entero, en una compra de VARIOS (02/10).

    Camilo y Lía: «primero se llena un anillo y después el otro». Con varios
    anillos, los campos del anillo de `Borrador` son los del que se está
    describiendo; al quedar completo pasa aquí y se empieza el siguiente. Los
    campos son los mismos y con el mismo nombre (`CAMPOS_DEL_ANILLO`).
    """

    pieza: str = ANILLO
    cantidad: int | None = None
    huellitas: list[HuellitaDelBorrador] = Field(default_factory=list)
    grabado: list[str] = Field(default_factory=list)
    sin_grabado: bool = False
    talla: float | None = None
    talla_revisar: bool = False
    talla_motivo: str = ""
    talla_rango: str = ""
    talla_confirmada: bool = False
    talla_fotos: list[str] = Field(default_factory=list)
    talla_escrita: str = ""


class Borrador(BaseModel):
    """Lo que la clienta ha decidido hasta ahora. Se guarda en el contexto."""

    #: «anillo», «cadena» (03/10) o «corazon» (17/10): la pieza que se está
    #: describiendo. La cadena lleva 1 huellita, no lleva talla y el nombre
    #: grabado es obligatorio (un renglón por lado, hasta 2 nombres por lado).
    #: El anillo de corazón es un anillo con UN corazón de circón en vez de
    #: huellitas: talla y grabado como cualquier anillo.
    pieza: str = ANILLO
    cantidad: int | None = None
    huellitas: list[HuellitaDelBorrador] = Field(default_factory=list)
    grabado: list[str] = Field(default_factory=list)
    sin_grabado: bool = False
    talla: float | None = None
    talla_revisar: bool = False
    #: De dónde salió la talla, para Lía: «estimada de 1.8 cm…», «confirmada
    #: por Lía». Vacío = la dijo ella con su número.
    talla_motivo: str = ""
    #: «entre 7½ y 8» cuando salió de una medida: es una referencia (27/09).
    talla_rango: str = ""
    #: Lía la confirmó o la corrigió desde el panel: desde ahí ES la talla.
    talla_confirmada: bool = False
    #: Regla de Lía (29/09): la talla la confirma ELLA, siempre, antes del
    #: abono. El bot mira la foto y hace una SUGERENCIA para el panel, pero no
    #: le dice ninguna talla a la clienta. Lo pone la asesora en cada turno
    #: (`TALLA_LA_CONFIRMA_LIA`); en False es el flujo de antes.
    talla_exige_lia: bool = False
    #: Las fotos que mandó para la talla (la regla), guardadas para que Lía
    #: las vea en el panel sin salir a buscarlas.
    talla_fotos: list[str] = Field(default_factory=list)
    #: La medida tal cual la escribió («1.8», «18 mm»), para Lía.
    talla_escrita: str = ""
    nombre_clienta: str = ""
    ciudad: str = ""
    #: A dónde va el anillo (con barrio / apto). Se pide DESPUÉS del abono y
    #: antes de despachar (regla de Camilo, 19/09); sin ella no se despacha.
    direccion: str = ""
    #: Lo recoge en Floridablanca en vez de envío: entonces no hace falta dirección.
    recoge: bool = False
    #: Pidió pagar el envío POR ADELANTADO (no está en casa, que se lo dejen en
    #: portería): se le cobra junto con el SALDO, cuando el anillo esté listo.
    #: Nunca con el abono. Lo normal —y lo que se dice si no pregunta— es
    #: pagarlo al recibir (Camilo, 21/09).
    envio_con_saldo: bool = False
    #: La cédula: la pide la transportadora para la guía. Se pregunta al final,
    #: con el resto de los datos de envío (Camilo, 20/09).
    cedula: str = ""
    #: El celular de contacto PARA LA GUÍA. Puede no ser el de WhatsApp (una
    #: clienta que manda el anillo a la casa de su mamá da el de la mamá).
    celular: str = ""
    #: A nombre de quién va la GUÍA, si no es ella («Natalia Bautista», su
    #: hermana). Vacío = a nombre de ella (29/09).
    destinatario: str = ""
    #: El barrio, aparte de la dirección (para ordenar y analizar).
    barrio: str = ""
    fecha_deseada: str = ""
    #: Lo que Lía tiene que mirar antes de fabricar.
    notas: list[str] = Field(default_factory=list)
    #: El pedido que nació de este borrador, cuando ya se pidió el abono.
    pedido_id: str | None = None
    pedido_codigo: str = ""
    #: La clienta dijo que ya pagó / mandó comprobante. Lo verifica una persona.
    abono_reportado: bool = False
    #: La clienta dice que pagó el SALDO (anillo listo). También lo verifica Lía.
    saldo_reportado: bool = False
    #: Lo que el turno anterior NO se pudo guardar o decir. Vuelve al modelo.
    avisos: list[str] = Field(default_factory=list)
    #: Acciones de «una sola vez» y en qué turno se hicieron (muestrario, guía,
    #: precios). Se pueden repetir, pero no en dos turnos seguidos.
    mostrado_en: dict[str, int] = Field(default_factory=dict)
    #: Ya se le mandaron las cuentas para el abono. Sin esto el modelo llegó a
    #: decir «ya te pasé los datos arriba» sin haberlos mandado nunca.
    cuentas_enviadas: bool = False
    #: Se le preguntó «¿1 o 2 huellitas?» y contestó solo «sí»: hasta que escriba
    #: una cantidad, el modelo no puede fijarla (cambia el precio).
    cantidad_en_duda: bool = False
    #: Mandó el comprobante con el anillo incompleto: apenas se complete, el
    #: pedido nace y el pago queda por revisar, sin volver a pedirle nada.
    pagado_sin_pedido: bool = False
    #: El último resumen que se le mostró, para no repetirlo idéntico.
    ultimo_resumen: str = ""
    #: Los últimos diseños que se le enseñaron, para no mandarle las mismas
    #: fotos dos turnos seguidos (20/09: repitió «Todo rosado» y «Todo rojo»
    #: cuando ella ya estaba hablando de la talla).
    ultimas_vistas: list[str] = Field(default_factory=list)
    #: Cuántos turnos lleva la conversación con la asesora.
    turnos: int = 0
    #: Cuántas veces se le ha preguntado la cantidad sin que ella escriba un
    #: número. A la tercera se le pasa a Lía en vez de seguir dando vueltas.
    veces_preguntando_cantidad: int = 0
    #: Lo que ella dijo que manda DESPUÉS («la medida te la confirmo en la
    #: tarde»): qué -> en qué turno. No se le vuelve a pedir en la charla; le
    #: llega UN recordatorio sobre eso y ya (Yulieth, 09/10: se la pidieron cuatro
    #: veces más). Se borra cuando lo da o cuando ella vuelve a hablar de eso.
    lo_manda_despues: dict[str, int] = Field(default_factory=dict)
    #: Mostró desinterés, por pequeño que sea («no me gusta la plata», «no los voy
    #: a pedir», «muy caro»), o la IA lo entendió así: NINGÚN recordatorio más en
    #: esta charla hasta que ella vuelva a mostrar interés (Camilo, 10/10).
    sin_recordatorios: bool = False
    #: Lo de `lo_manda_despues` que ya tuvo su recordatorio: no lleva otro.
    recordado_despues: list[str] = Field(default_factory=list)
    #: Lo SEPARA con el abono y la talla la manda después (Camilo, 13/10: «la
    #: talla no debe frenar»). El abono ya no espera la talla; el pedido nace
    #: con «Talla: me la mandas después» y Lía no lo funde hasta tenerla (R7).
    talla_despues: bool = False
    #: Cuántas veces se le pidió cada cosa sin que la diera. A la segunda se
    #: deja de pedir en la charla: lo retoma el recordatorio (`VECES_QUE_SE_PIDE`).
    veces_pedido: dict[str, int] = Field(default_factory=dict)
    #: Ya se llamó a Lía porque pagó con el pedido a medias. Se hace UNA vez:
    #: escalar en cada turno le llena la bandeja del mismo aviso.
    llamada_por_pago_incompleto: bool = False
    #: Compra VARIOS anillos (02/10). Se preguntan DE A UNO y en orden: hasta
    #: que uno no está completo no se pasa al siguiente; el abono y el saldo
    #: se cobran juntos, de todos (regla de Lía). Los campos del anillo de
    #: arriba son los del que va; `anillos` son los ya completos (antes) y
    #: `por_empezar` los que vienen después, que pueden traer ya lo que ella
    #: adelantó de ellos («talla 6 el de una»).
    anillos: list[AnilloListo] = Field(default_factory=list)
    por_empezar: list[AnilloListo] = Field(default_factory=list)
    #: Dijo que todos los anillos son de la misma talla: se pregunta una vez.
    misma_talla: bool = False
    #: Durante UN turno, el anillo del que habló ella ocupa el lugar del actual
    #: (`enfocar`). No se guarda: al final del turno se deshace.
    _foco: int | None = PrivateAttr(default=None)

    # -- varios anillos -------------------------------------------------------

    @property
    def anillos_total(self) -> int:
        return len(self.anillos) + 1 + len(self.por_empezar)

    @property
    def es_cadena(self) -> bool:
        return self.pieza == CADENA

    @property
    def es_corazon(self) -> bool:
        return self.pieza == CORAZON

    @property
    def varios(self) -> bool:
        return self.anillos_total > 1

    @property
    def numero_del_anillo(self) -> int:
        """Cuál se está describiendo (1, 2, 3…)."""
        return len(self.anillos) + 1

    def anillo_actual(self) -> AnilloListo:
        return AnilloListo.model_validate(self.model_dump(include=set(CAMPOS_DEL_ANILLO)))

    def _guardado(self, i: int) -> AnilloListo | None:
        """El anillo `i` si NO es el actual (los completos y los que vienen)."""
        actual = len(self.anillos)
        if i < actual:
            return self.anillos[i]
        if i > actual and i - actual - 1 < len(self.por_empezar):
            return self.por_empezar[i - actual - 1]
        return None

    def vista(self, i: int) -> Borrador:
        """El anillo `i` (desde 0) como un borrador de UN anillo, con lo de la
        clienta. Sirve para su resumen, su personalización y sus ediciones."""
        datos = self.model_dump(exclude={"anillos", "por_empezar", "misma_talla"})
        if (guardado := self._guardado(i)) is not None:
            datos.update(guardado.model_dump())
        return Borrador.model_validate(datos)

    def vistas(self) -> list[Borrador]:
        """Todos los anillos, en el orden de ELLA (aunque haya uno enfocado)."""
        vistas = [self.vista(i) for i in range(self.anillos_total)]
        if self._foco is not None:
            a = len(self.anillos)
            vistas[a], vistas[self._foco] = vistas[self._foco], vistas[a]
        return vistas

    @property
    def posicion_actual(self) -> int:
        """Dónde está, en el orden de ella, el anillo que ocupa el lugar actual."""
        return self._foco if self._foco is not None else len(self.anillos)

    def enfocar(self, i: int | None) -> None:
        """Lo de este turno es del anillo `i`: ocupa el lugar del actual."""
        if i is None or i == len(self.anillos) or self._foco is not None:
            return
        self.intercambiar(i)
        self._foco = i

    def desenfocar(self) -> None:
        if self._foco is not None:
            i, self._foco = self._foco, None
            self.intercambiar(i)

    def poner_anillo(self, i: int, vista: Borrador | AnilloListo) -> None:
        """Guarda en el anillo `i` lo que es del anillo en `vista`."""
        anillo = AnilloListo.model_validate(
            vista.model_dump(include=set(CAMPOS_DEL_ANILLO))
        )
        actual = len(self.anillos)
        if i < actual:
            self.anillos[i] = anillo
        elif i > actual:
            self.por_empezar[i - actual - 1] = anillo
        else:
            for campo in CAMPOS_DEL_ANILLO:
                setattr(self, campo, getattr(anillo, campo))

    def intercambiar(self, i: int) -> None:
        """Pone el anillo `i` en el lugar del actual (y el actual en el suyo).

        Es para anotar lo que ella dijo de OTRO anillo («para el de tres: …»)
        con las mismas reglas de siempre; se deshace llamándolo otra vez."""
        actual = len(self.anillos)
        if i == actual or self._guardado(i) is None:
            return
        otro, este = self.vista(i), self.anillo_actual()
        self.poner_anillo(actual, otro)
        self.poner_anillo(i, este)

    def agregar_anillo(self, cantidad: int | None = None) -> None:
        self.por_empezar.append(AnilloListo(cantidad=cantidad))

    def pasar_al_siguiente(self) -> bool:
        """El anillo que va quedó completo y vienen otros: se guarda y empieza
        el siguiente, con lo que ella ya haya adelantado de él (y la talla, si
        dijo que todos son de la misma)."""
        if not self.por_empezar or self.falta_del_anillo():
            return False
        terminado = self.anillo_actual()
        self.anillos.append(terminado)
        siguiente = self.por_empezar.pop(0)
        sin_talla = siguiente.talla is None and not (
            siguiente.talla_fotos or siguiente.talla_escrita
        )
        if self.misma_talla and sin_talla:
            for campo in CAMPOS_DE_LA_TALLA:
                setattr(siguiente, campo, getattr(terminado, campo))
        self.poner_anillo(len(self.anillos), siguiente)
        self.cantidad_en_duda = False
        self.veces_preguntando_cantidad = 0
        self.ultimas_vistas = []
        return True

    def quitar_un_anillo(self) -> None:
        """Al final es un anillo menos: primero sale el último que no se ha
        empezado; si no queda ninguno, el que se estaba describiendo (y el
        último completo vuelve a ser el actual)."""
        if self.por_empezar:
            self.por_empezar.pop()
        elif self.anillos:
            ultimo = self.anillos.pop()
            self.poner_anillo(len(self.anillos), ultimo)
        if not self.varios:
            self.misma_talla = False

    def igualar_tallas(self) -> None:
        """Con «todos de la misma talla», la del anillo que la tenga va a todos."""
        if not self.misma_talla or not self.varios:
            return
        actual = self.vista(len(self.anillos))
        con_talla = [
            v
            for v in [actual, *self.vistas()]
            if v.talla is not None or v.talla_fotos or v.talla_escrita
        ]
        if not con_talla:
            return
        fuente = con_talla[0]
        for i in range(self.anillos_total):
            v = self.vista(i)
            if v.es_cadena:
                continue  # la cadena no lleva talla
            for campo in CAMPOS_DE_LA_TALLA:
                setattr(v, campo, getattr(fuente, campo))
            self.poner_anillo(i, v)

    def pendiente_de_talla(self) -> int | None:
        """El primer anillo (desde 0) cuya talla espera a Lía, o None."""
        if not self.talla_exige_lia:
            return None
        for i, a in enumerate(self.vistas()):
            if not a.talla_confirmada and (
                a.talla is not None or a.talla_fotos or a.talla_escrita
            ):
                return i
        return None

    def fijar_talla(self, i: int | None, talla: float, motivo: str) -> None:
        """Lía confirmó o corrigió la talla del anillo `i` (None = el que espera,
        o el actual). Con «misma talla», la de todos."""
        if i is None:
            i = self.pendiente_de_talla()
        if i is None:
            i = len(self.anillos)
        todos = range(self.anillos_total) if self.misma_talla else [i]
        for k in todos:
            v = self.vista(k)
            v.talla, v.talla_revisar, v.talla_confirmada = talla, False, True
            v.talla_rango, v.talla_motivo = "", motivo
            self.poner_anillo(k, v)

    def anillos_del_pedido(self) -> list[tuple[int, Personalizacion, list[str]]]:
        """Cada anillo como entra al pedido: (huellitas, personalización, notas).

        Las notas generales (`notas`) NO van aquí: son del pedido, una vez."""
        salida = []
        for k, v in enumerate(self.vistas(), 1):
            v.notas = []
            personalizacion, notas = v.a_personalizacion()
            if self.varios:
                notas = [f"Anillo {k}: {n}" for n in notas]
            salida.append((v.cantidad or len(v.huellitas) or 1, personalizacion, notas))
        return salida

    def falta_del_anillo(self) -> list[str]:
        """Lo que falta del ANILLO, EN EL ORDEN EN QUE SE PREGUNTA.

        El orden importa y es el de Camilo (20/09): cantidad → TALLA → colores
        → grabado. La talla va segunda, apenas dice de cuántas huellitas lo
        quiere, porque es lo único que necesita un paso de la clienta (medir un
        anillo con una regla y mandar la foto). Preguntándola al final, como se
        hacía antes, se llegaba al abono con «Talla: por confirmar» y el pedido
        se quedaba parado justo cuando ya había pagado.

        Escoger colores y grabado es la parte divertida: mientras ella mide,
        eso sigue avanzando.
        """
        if self.es_cadena:
            # La cadena (03/10): una huellita, sin talla, el nombre SIEMPRE.
            falta = []
            if not (self.huellitas and self.huellitas[0].completa):
                falta.append("colores")
            if not self.grabado:
                falta.append("grabado")
            return falta
        falta = []
        if self.cantidad is None and not self.es_corazon:
            falta.append("cantidad de huellitas")
        # Con la regla de Lía, si ya mandó la foto (aunque no se haya podido
        # leer) la talla no se le vuelve a pedir: la decide Lía al verla.
        if (
            self.talla is None
            and not self.talla_despues
            and not (self.talla_exige_lia and (self.talla_fotos or self.talla_escrita))
        ):
            falta.append("talla")
        if self.es_corazon:
            # Un solo color: el del corazón.
            if not (self.huellitas and self.huellitas[0].corazon is not None):
                falta.append("colores")
        elif self.cantidad is not None and (
            len(self.huellitas) < self.cantidad
            or not all(h.completa for h in self.huellitas[: self.cantidad])
        ):
            falta.append("colores")
        if not self.grabado and not self.sin_grabado:
            falta.append("grabado")
        return falta

    def falta_de_quien(self) -> list[str]:
        """Lo único personal que se pregunta antes del abono: su nombre.

        Sirve para hablarle por su nombre al confirmar el pedido. Todo lo demás
        —ciudad, cédula, celular, dirección— se pide al final (`falta_de_la_guia`).
        """
        return [] if self.nombre_clienta.strip() else ["nombre completo"]

    def falta_de_la_guia(self) -> list[str]:
        """Los datos de envío, EN EL ORDEN EN QUE SE PIDEN en el mensaje de Lía.

        Regla de Camilo (20/09): NO se piden al principio. Van al final, cuando
        el anillo ya está hecho, en el mismo mensaje que lleva las fotos y el
        cobro del saldo — porque es ahí cuando ella los va a mandar junto con la
        transferencia.

        Pedirlos antes es un formulario a alguien que todavía no ha comprado; y
        además envejecen: entre que encarga y recibe pasan dos semanas y bien
        puede haberse mudado o preferir que llegue a otra parte.
        """
        if self.recoge:
            return [] if self.nombre_clienta.strip() else ["nombre completo"]
        falta = []
        if not self.ciudad.strip():
            falta.append("ciudad")
        if not (self.destinatario or self.nombre_clienta).strip():
            falta.append("nombre completo")
        if not self.cedula.strip():
            falta.append("cédula")
        if not self.celular.strip():
            falta.append("celular")
        if not self.direccion.strip():
            falta.append("dirección completa con barrio y nomenclatura")
        return falta

    def falta_para_despachar(self) -> list[str]:
        """Lo que falta para ENTREGARLO: los datos de la guía, o que lo recoge."""
        return self.falta_de_la_guia()

    def falta_para_abono(self) -> list[str]:
        """Lo que falta para pedir el abono: el anillo completo —con talla— y su
        nombre. Nada más.

        Regla de Camilo (20/09): los datos de envío NO se piden antes de pagar;
        van al final, con las fotos del anillo terminado (`falta_de_la_guia`).
        Un pedido que se paga a medias se queda «en abono»: no nace ni entra al
        taller hasta tener lo de aquí (ver `pagado_sin_pedido`).
        """
        falta = self.falta_del_anillo()
        # Con varios anillos, los otros que no están completos van después del
        # actual: se preguntan de a uno, cuando les toque.
        if self.varios:
            actual = self.posicion_actual
            falta += [
                f"{ANILLO_SIGUIENTE} {i + 1} de {self.anillos_total}"
                for i, v in enumerate(self.vistas())
                if i != actual and v.falta_del_anillo()
            ]
        falta += self.falta_de_quien()
        # Va AL FINAL a propósito: lo demás se le sigue preguntando a ella
        # mientras Lía revisa; esto es lo último que queda (regla de Lía).
        if self.talla_por_confirmar and "talla" not in falta:
            falta.append(TALLA_DE_LIA)
        return falta

    @property
    def talla_por_confirmar(self) -> bool:
        """¿Hay una talla (o una foto de la regla) esperando que Lía la mire?

        De CUALQUIER anillo de la compra: el abono espera a que estén todas."""
        return self.pendiente_de_talla() is not None

    def resumen(self) -> str:
        """El resumen que Lía manda antes del abono, con su mismo formato.

        Con varios anillos, uno debajo del otro, cada uno con su título."""
        if self.varios or self.anillos:
            vistas = self.vistas()
            cadenas = sum(v.es_cadena for v in vistas)
            anillos = len(vistas) - cadenas
            if not cadenas:
                lineas = [f"•Pedido de {len(vistas)} anillos•"]
            else:
                partes = [
                    f"{n} {nombre}{'s' if n > 1 else ''}"
                    for n, nombre in ((anillos, "anillo"), (cadenas, "cadena"))
                    if n
                ]
                lineas = [f"•Pedido: {' y '.join(partes)}•"]
            k = 0
            for v in vistas:
                if not v.es_cadena:
                    k += 1
                prefijo = "Cadena" if v.es_cadena else f"Anillo {k}: "
                lineas += ["", *v._lineas_del_anillo(prefijo)]
        else:
            lineas = self._lineas_del_anillo()
        if self.nombre_clienta or self.direccion or self.ciudad or self.recoge:
            lineas.append("")
            lineas.append("•Entrega•")
            if self.nombre_clienta:
                lineas.append(f"A nombre de: {self.nombre_clienta}")
            if self.recoge:
                lineas.append("Lo recoges en Floridablanca")
            else:
                destino = ", ".join(p for p in (self.direccion, self.ciudad) if p)
                if destino:
                    lineas.append(f"Envío a: {destino}")
        return "\n".join(lineas)

    def _lineas_del_anillo(self, prefijo: str = "") -> list[str]:
        """El bloque de UN anillo en el resumen. Sin prefijo es el de siempre."""
        if self.es_corazon:
            titulo = f"•{prefijo}corazón•" if prefijo else "•Anillo de corazón•"
            lineas = [titulo] if prefijo else [titulo, ""]
            lineas.append(
                f"Talla: {talla_texto(self.talla)}"
                if self.talla is not None
                else "Talla: me la mandas después 📏"
                if self.talla_despues
                else "Talla: por confirmar"
            )
            h = self.huellitas[0] if self.huellitas else None
            if h is not None and h.corazon is not None:
                lineas.append(
                    f"Color del corazón: {EMOJI_COLOR[h.corazon]} {_bonito(h.corazon)}"
                )
            if self.grabado:
                lineas.append("Grabado: " + unir_grabado(self.grabado))
            elif self.sin_grabado:
                lineas.append("Grabado: sin grabado")
            return lineas
        if self.es_cadena:
            titulo = "•Cadena con huellita•"
            lineas = [titulo] if prefijo else [titulo, ""]
            if self.huellitas:
                lineas.append("Color: " + self.huellitas[0].describir())
            if self.grabado:
                lineas.append("Grabado: " + texto_del_grabado(self.grabado, CADENA))
            return lineas
        n = self.cantidad or len(self.huellitas) or 1
        titulo = f"•{prefijo or 'Anillo '}{n} huellita{'s' if n > 1 else ''}•"
        # El renglón en blanco debajo del título es parte del formato: separa
        # el encabezado de los datos y hace que se lea de un vistazo. Con
        # varios anillos el título ya va separado por el renglón de arriba.
        lineas = [titulo] if prefijo else [titulo, ""]
        lineas.append(
            f"Talla: {talla_texto(self.talla)}"
            if self.talla is not None
            else "Talla: me la mandas después 📏"
            if self.talla_despues
            else "Talla: por confirmar"
        )
        for i, h in enumerate(self.huellitas[:n], 1):
            lineas.append((f"Huellita {i}: " if n > 1 else "Color: ") + h.describir())
        if self.grabado:
            lineas.append("Grabado: " + unir_grabado(self.grabado))
        elif self.sin_grabado:
            lineas.append("Grabado: sin grabado")
        return lineas

    def a_personalizacion(self) -> tuple[Personalizacion, list[str]]:
        """Lo que se guarda en el pedido, y lo que Lía tiene que completar a mano.

        Un renglón de grabado que el taller no admite NO tumba el pedido: va a
        las notas. Perder la venta por un símbolo sería peor que preguntarlo.
        """
        notas = list(self.notas)
        huellitas = []
        for i, h in enumerate(self.huellitas[: self.cantidad or len(self.huellitas)], 1):
            if self.es_corazon and h.corazon is not None:
                # El corazón es una sola piedra: su color va en las dos casillas.
                huellitas.append(Huellita(corazon=h.corazon, dedos=h.corazon))
                break
            if not h.completa:
                continue
            huellitas.append(
                Huellita(
                    corazon=h.corazon,
                    dedos=h.dedos or h.dedos_alternos[0],
                    dedos_alternos=list(h.dedos_alternos),
                )
            )
            if len(h.dedos_alternos) == 4:
                # Va en el pedido, pero también en las notas: en una huellita de
                # cuatro colores, que el taller lo lea dos veces no sobra.
                notas.append(f"Huellita {i}: deditos alternos {h.describir()}")
            if h.mascota:
                notas.append(f"Huellita {i} es de {h.mascota}")
        grabados = list(self.grabado)
        try:
            Personalizacion(grabados=grabados, pieza=self.pieza)
        except ValueError as exc:
            notas.append(f"Grabado pedido: {' | '.join(grabados)} — revisar ({exc})")
            grabados = []
        personalizacion = Personalizacion(
            pieza=self.pieza,
            talla=None if self.es_cadena else self.talla,
            talla_revisar=self.talla_revisar,
            talla_motivo=self.talla_motivo
            or ("la escribió la clienta" if self.talla_revisar else ""),
            huellitas=huellitas,
            grabados=grabados,
            sin_grabado=self.sin_grabado,
        )
        return personalizacion, notas


#: Cuando pide consejo («¿cuál me recomiendas?»): estos cuatro, cada uno de un
#: solo color en toda la huellita. Regla de Camilo (19/09); solo si lo pide.
SUGERENCIAS: tuple[ColorCircon, ...] = (
    ColorCircon.ROSADO,
    ColorCircon.AZUL_REY,
    ColorCircon.BLANCO,
    ColorCircon.AMARILLO,
)


def pie_de_sugerencia(color: ColorCircon) -> str:
    """«Todo rosa»: con el nombre VIGENTE de la bolsita (panel → Colores)."""
    from app.domain.personalizacion import NOMBRE_COLOR

    return f"Todo {NOMBRE_COLOR[color]}"


def unir_grabado(renglones: list[str]) -> str:
    """«Luna» + «Mara» -> «Luna ♡ Mara»: corazones ENTRE los nombres (Lía, 02/10).

    La regla vive en `personalizacion.unir_grabados`, para que el resumen, el
    taller, el panel y el ERP lo escriban igual."""
    return unir_grabados(renglones)


def _bonito(color: ColorCircon | None) -> str:
    return NOMBRE_COLOR[color].capitalize() if color else ""


# ══════════════════════════════════════════════════════════════════════════
#  LA JUGADA: lo que devuelve el modelo, con esquema cerrado
# ══════════════════════════════════════════════════════════════════════════


class Confianza(str, Enum):
    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAJA = "BAJA"


class AccionAsesora(str, Enum):
    """Lo que la asesora puede pedir que pase. Python decide si pasa.

    MOSTRAR_COMO_QUEDA casi nunca lo pide el modelo: Python lo manda solo apenas
    quedan los colores (regla de Camilo: la clienta no tiene que pedirlo).
    """

    MOSTRAR_PRECIOS = "MOSTRAR_PRECIOS"  # la ficha del anillo con los 3 precios
    MOSTRAR_MUESTRARIO = "MOSTRAR_MUESTRARIO"  # foto de los 14 colores
    MOSTRAR_GUIA_TALLA = "MOSTRAR_GUIA_TALLA"  # cómo medirse la talla
    MOSTRAR_EJEMPLOS = "MOSTRAR_EJEMPLOS"  # fotos y video de anillos hechos
    MOSTRAR_COMO_QUEDA = "MOSTRAR_COMO_QUEDA"  # previsualización con sus colores
    MOSTRAR_SUGERENCIAS = "MOSTRAR_SUGERENCIAS"  # pide consejo: 4 diseños de un color
    MOSTRAR_RESUMEN = "MOSTRAR_RESUMEN"  # el resumen del anillo para confirmar
    PEDIR_ABONO = "PEDIR_ABONO"  # pedido 100 % confirmado: lo crea y manda cuentas
    MANDAR_CUENTAS = "MANDAR_CUENTAS"  # pregunta cómo pagar: solo las cuentas
    RECIBIR_COMPROBANTE = "RECIBIR_COMPROBANTE"  # dijo que pagó / mandó soporte
    PASAR_A_LIA = "PASAR_A_LIA"  # queja, caso raro, o lo pide
    QUITAR_COLORES = "QUITAR_COLORES"  # «ya no me gustó» y todavía no dice cuál
    # Pide pagar el envío ANTES de recibir (no está en casa, portería): va con
    # el SALDO. Es una acción y no un campo de `CambiosDelBorrador` a propósito:
    # un campo opcional más y el proveedor rechaza el esquema entero («Schema is
    # too complex», 21/09) — el bot se quedaría sin modelo.
    ENVIO_CON_SALDO = "ENVIO_CON_SALDO"
    ENVIO_AL_RECIBIR = "ENVIO_AL_RECIBIR"  # se arrepiente: lo paga al recibir
    # Compra VARIOS anillos (02/10). Acciones y no campos, por lo mismo de arriba.
    OTRO_ANILLO = "OTRO_ANILLO"  # quiere un anillo MÁS aparte del que se describe
    UN_ANILLO_MENOS = "UN_ANILLO_MENOS"  # al final es un anillo menos
    MISMA_TALLA = "MISMA_TALLA"  # todos sus anillos son de la misma talla
    # La cadena (03/10): NUNCA se ofrece; solo si ella pregunta (Python lo exige).
    MOSTRAR_CADENA = "MOSTRAR_CADENA"  # preguntó por cadenas u otros productos
    ES_CADENA = "ES_CADENA"  # la pieza que quiere (o la que se describe) es la cadena
    # El anillo de corazón (17/10): SÍ se puede ofrecer, desde el primer mensaje.
    MOSTRAR_CORAZON = "MOSTRAR_CORAZON"  # su presentación: precio y fotos
    ES_CORAZON = "ES_CORAZON"  # la pieza que quiere es el anillo de corazón


def acordar_envio(
    b: Borrador, acciones: list[AccionAsesora]
) -> tuple[Borrador, list[str]]:
    """Cuándo paga el envío, según lo que pidió en este turno. Python decide.

    Lo normal es al recibir. Si ella pide pagarlo antes, va con el saldo; si
    lo recoge en la tienda, no hay envío que pagar.
    """
    rechazos: list[str] = []
    if AccionAsesora.ENVIO_AL_RECIBIR in acciones:
        b.envio_con_saldo = False
    elif AccionAsesora.ENVIO_CON_SALDO in acciones:
        if b.recoge:
            rechazos.append("lo recoge en la tienda: no hay envío que pagar")
        else:
            b.envio_con_saldo = True
    return b, rechazos


ACCIONES_DE_LOS_ANILLOS = frozenset(
    {
        AccionAsesora.ES_CADENA,
        AccionAsesora.ES_CORAZON,
        AccionAsesora.OTRO_ANILLO,
        AccionAsesora.UN_ANILLO_MENOS,
        AccionAsesora.MISMA_TALLA,
    }
)
_ANILLOS_ESCRITOS = re.compile(r"\b(2|3|4|5|dos|tres|cuatro|cinco)\s+anillos\b", re.I)
_EN_NUMERO_DE_ANILLOS = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}
#: Lo que respalda OTRO_ANILLO en lo que ELLA escribió. Sin esto, el modelo
#: repitiendo la acción un turno después sumaría un anillo que nadie pidió.
_HABLA_DE_OTRO_ANILLO = re.compile(
    r"\b(otro|otra|otros|anillos|tambien|aparte|ademas|segundo|tercer\w*|"
    r"uno mas|dos|tres|cuatro|cinco)\b",
    re.I,
)
_HABLA_DE_MISMA_TALLA = re.compile(
    r"\b(mism[oa]s?|igual(es)?|los dos|las dos|ambos|ambas|todos|todas)\b", re.I
)
_HABLA_DE_UNO_MENOS = re.compile(
    r"\b(solo|sola|solamente|ya no|mejor|quit\w*|sin el|uno solo|un solo|"
    r"cancel\w*|no quiero|al final|nada mas)\b",
    re.I,
)


def anillos_que_escribio(texto: str | None) -> int | None:
    """«Son dos anillos», «3 anillos»: cuántos dijo, si lo dijo."""
    m = _ANILLOS_ESCRITOS.search(_sin_tildes(texto or ""))
    if not m:
        return None
    crudo = m.group(1).lower()
    return int(crudo) if crudo.isdigit() else _EN_NUMERO_DE_ANILLOS[crudo]


#: Que COMPRA varios («quiero dos anillos», «serían dos anillos», «mando a hacer
#: dos anillos», «2 anillos, uno para mí y otro para…»): no basta nombrarlos.
_PIDE_VARIOS_ANILLOS = re.compile(
    r"\b(?:quiero|quisiera|serian|seran|son|necesito|pido|encargo|hazme|haceme"
    r"|mando\s+a\s+hacer|mandar\s+a\s+hacer|voy\s+a\s+pedir|vamos\s+a\s+pedir"
    r"|me\s+(?:haces|hacen|gustarian))\b[^.?!]{0,20}?"
    r"\b(2|3|4|5|dos|tres|cuatro|cinco)\s+anillos\b",
    re.I,
)


def anillos_que_pide(texto: str | None) -> int | None:
    """Cuántos anillos dice que COMPRA (no solo que los nombra)."""
    m = _PIDE_VARIOS_ANILLOS.search(_sin_tildes(texto or ""))
    if not m:
        return None
    crudo = m.group(1).lower()
    return int(crudo) if crudo.isdigit() else _EN_NUMERO_DE_ANILLOS[crudo]


def contar_anillos(
    b: Borrador,
    acciones: list[AccionAsesora],
    texto: str | None,
    cambios: CambiosDelBorrador,
    *,
    hay_pedido: bool,
    ultimo_de_lia: str = "",
    cadena_mostrada: bool = False,
    corazon_mostrado: bool = False,
) -> tuple[list[str], str, CambiosDelBorrador, int]:
    """Cuántos anillos compra, según lo que pidió en este turno. Python decide.

    Devuelve (lo que no pasó, nota para Lía, los cambios, cuántos se sumaron).
    El modelo propone con las acciones; lo que ella escribió lo respalda. Con
    el pedido ya creado no se cambia: otro anillo es otro pedido (lo ve Lía).

    «3» y luego «y otro de 1»: el 1 es del anillo NUEVO. El modelo lo anotaba
    como la cantidad del que iba y el de 3 se perdía (ensayo del 02/10).
    """
    rechazos: list[str] = []
    nota = ""
    nuevos = 0
    limpio = _sin_tildes(texto or "")
    if AccionAsesora.OTRO_ANILLO in acciones:
        escrito = anillos_que_escribio(limpio)
        if hay_pedido:
            rechazos.append(
                "su pedido ya está creado: el otro anillo es un pedido aparte y lo "
                "toma Lía; dile que ya le avisas"
            )
            nota = "La clienta quiere OTRO anillo con el pedido ya creado: tómaselo"
        elif not (escrito or _HABLA_DE_OTRO_ANILLO.search(limpio)):
            rechazos.append("ella no habló de otro anillo: no se sumó ninguno")
        else:
            # Si dijo cuántos son, son ESOS: si ya están (los creó lo que ella
            # dijo, `anillos_que_pide`), no se suma otro (12/10: salían tres).
            total = max(escrito, b.anillos_total) if escrito else b.anillos_total + 1
            if total > MAX_ANILLOS:
                rechazos.append(
                    f"más de {MAX_ANILLOS} anillos es un pedido de mayorista: lo ve Lía"
                )
                nota = f"La clienta quiere {total} anillos: pedido grande, atiéndelo tú"
            else:
                del_nuevo = _huellitas_de(_OTRO_DE.search(limpio))
                propuesta = cambios.cantidad_huellitas
                if propuesta is not None and (
                    propuesta == del_nuevo or (b.cantidad and propuesta != b.cantidad)
                ):
                    # Esa cantidad es la del anillo nuevo, no la del que iba.
                    del_nuevo = del_nuevo or propuesta
                    cambios = cambios.model_copy(update={"cantidad_huellitas": None})
                if b.cantidad is None and cambios.cantidad_huellitas is None:
                    primero = _huellitas_de(_UNO_DE.search(limpio))
                    if primero:
                        cambios = cambios.model_copy(
                            update={"cantidad_huellitas": primero}
                        )
                while b.anillos_total < total:
                    b.agregar_anillo(del_nuevo if nuevos == 0 else None)
                    nuevos += 1
    if AccionAsesora.UN_ANILLO_MENOS in acciones:
        if hay_pedido:
            rechazos.append("su pedido ya está creado: quitar un anillo lo hace Lía")
            nota = "La clienta quiere quitar un anillo del pedido ya creado"
        elif not b.varios:
            rechazos.append("solo hay un anillo: no se quitó nada")
        elif not _HABLA_DE_UNO_MENOS.search(limpio):
            rechazos.append("ella no dijo que quiere un anillo menos: no se quitó")
        else:
            b.quitar_un_anillo()
    if AccionAsesora.MISMA_TALLA in acciones and b.varios:
        # Lo tiene que decir ella, o decir «sí» a una pregunta por la misma
        # talla. En el ensayo del 02/10 un «sí» a «¿y el de 3?» se leyó como
        # «los dos de la misma», y la talla de uno se le puso al otro.
        if _HABLA_DE_MISMA_TALLA.search(limpio) or (
            solo_afirma(texto) and "misma" in _sin_tildes(ultimo_de_lia).lower()
        ):
            b.misma_talla = True
        else:
            rechazos.append(
                "ella no dijo que todos son de la misma talla: pregúntaselo claro"
            )
    if AccionAsesora.ES_CADENA in acciones:
        if hay_pedido:
            rechazos.append(
                "su pedido ya está creado: la cadena es un pedido aparte y lo toma Lía"
            )
            nota = "La clienta quiere la cadena con el pedido ya creado: tómaselo"
        elif not (habla_de_cadena(limpio) or cadena_mostrada):
            rechazos.append(
                "ella no habló de la cadena: no se anotó (nunca se ofrece por cuenta "
                "propia)"
            )
        else:
            nuevos += _anotar_la_pieza(b, limpio, nuevos, CADENA)
    if AccionAsesora.ES_CORAZON in acciones:
        if hay_pedido:
            rechazos.append(
                "su pedido ya está creado: el anillo de corazón es un pedido aparte y "
                "lo toma Lía"
            )
            nota = "La clienta quiere el anillo de corazón con el pedido ya creado"
        elif not (habla_del_corazon(limpio) or corazon_mostrado):
            rechazos.append(
                "ella no habló del anillo de corazón: no se anotó (el «corazón» de "
                "una huellita es otra cosa: la piedra grande de la patita)"
            )
        else:
            nuevos += _anotar_la_pieza(b, limpio, nuevos, CORAZON)
    elif b.es_corazon and not hay_pedido and _VUELVE_A_HUELLITAS.search(limpio):
        # «Mejor el de huellitas»: vuelve a ser el anillo de siempre.
        b.pieza, b.cantidad = ANILLO, None
    return rechazos, nota, cambios, nuevos


#: «el de una», «para el de 3», «la de una huella», «el anillo de dos»: de cuál
#: anillo habla, por sus huellitas. No «de 1,8 cm».
_EL_DE = re.compile(
    r"\b(?:el|la|del|al|para el|para la|en el|en la)\s+(?:anillo\s+)?de\s+"
    r"(1|un|una|uno|2|dos|3|tres)\b(?!\s*[.,]?\d)(?!\s*(?:cm|mm|centi|mili))",
    re.I,
)
_OTRO_DE = re.compile(
    r"\b(?:otro|otra)\s+(?:anillo\s+)?de\s+(1|un|una|uno|2|dos|3|tres)\b", re.I
)
_UNO_DE = re.compile(r"\b(?:uno|un anillo)\s+de\s+(1|una|2|dos|3|tres)\b", re.I)
_ORDINAL = re.compile(r"\b(primer|primero|segundo|tercer|tercero|cuarto|quinto)\b", re.I)
_POSICION = {"primer": 0, "primero": 0, "segundo": 1, "tercer": 2, "tercero": 2}
_POSICION |= {"cuarto": 3, "quinto": 4}


def _huellitas_de(m: re.Match | None) -> int | None:
    if not m:
        return None
    return _EN_NUMERO.get(m.group(1).lower())


def _tiene_talla(v: Borrador) -> bool:
    return v.talla is not None or bool(v.talla_fotos or v.talla_escrita)


#: «talla 6», «tallas 6 y 8», «la talla 7 y medio», «talla 6.5».
_UNA_TALLA = re.compile(
    r"\btallas?\s+(?:la\s+|el\s+|de\s+)?(\d{1,2})(?:[.,](5)\b|\s*y\s*medi[ao]\b)?",
    re.I,
)
_Y_OTRA_TALLA = re.compile(
    r"\A\s*(?:y|,)\s*(?:la\s+|el\s+)?(\d{1,2})(?:[.,](5)\b|\s*y\s*medi[ao]\b)?", re.I
)


def tallas_escritas(texto: str | None) -> list[float]:
    """Las tallas que ESCRIBIÓ, en orden: «el mío talla 6 y el de ella talla 8»
    -> [6, 8]; «tallas 7 y medio y 9» -> [7.5, 9]. Solo las que existen."""
    limpio = _sin_tildes(texto or "")
    tallas: list[float] = []

    def anotar(m: re.Match) -> None:
        medio = m.group(2) or re.search(r"medi[ao]", m.group(0), re.I)
        valor = float(m.group(1)) + (0.5 if medio else 0)
        if valor in DIAMETRO_MM:
            tallas.append(valor)

    for m in _UNA_TALLA.finditer(limpio):
        anotar(m)
        resto = limpio[m.end() :]
        while (y := _Y_OTRA_TALLA.search(resto)) is not None:
            anotar(y)
            resto = resto[y.end() :]
    return tallas


def tallas_para_varios(b: Borrador, texto: str | None) -> list[tuple[int, float]]:
    """Con varios anillos, las tallas que dio de una vez, a qué anillo va cada una.

    Pasó en la prueba de verdad (04/10): «el mío talla 6 y el de ella talla 8»
    -> se anotó la 6 y al de la hermana le pidió la foto de la regla. El modelo
    solo puede devolver UNA talla por turno (el esquema no admite más), así que
    Python las lee del texto: en el orden en que las dijo, a los anillos en su
    orden. Si dijo tantas como anillos, una a cada uno; si dijo tantas como los
    que todavía no tienen talla, a esos. Si no cuadra, nada (decide el modelo).
    """
    if not b.varios or b._foco is not None:
        return []
    tallas = tallas_escritas(texto)
    if len(tallas) < 2:
        return []
    anillos = [i for i in range(b.anillos_total) if not b.vista(i).es_cadena]
    if len(tallas) == len(anillos):
        return list(zip(anillos, tallas, strict=True))
    sin_talla = [i for i in anillos if b.vista(i).talla is None]
    if len(tallas) == len(sin_talla):
        return list(zip(sin_talla, tallas, strict=True))
    return []


#: «los dos de una huellita», «ambos de 2 huellitas», «las tres de una».
#: Y como lo escribió Yulieth (09/10): «cada anillo CON una sola HUELLA».
_CANTIDAD_DE_TODOS = re.compile(
    r"\b(?:(?:los|las)\s+(?:dos|tres|cuatro|2|3|4)|ambos|ambas|todos|todas"
    r"|cada\s+uno|cada\s+una|cada\s+anillo)\b[^.?!]{0,30}?\b(?:de|con)\s+"
    r"(una|uno|1|dos|2|tres|3)(?:\s+(?:sola\s+)?huell\w*)?\b",
    re.I,
)
#: «En los dos anillos / Khalifa», «para ambos», «el mismo nombre en los dos»:
#: el grabado va en TODOS (Yulieth: se le volvió a preguntar para el segundo).
_GRABADO_DE_TODOS = re.compile(
    r"\b(?:en|para|a)\s+(?:los\s+(?:dos|tres|2|3)|las\s+(?:dos|tres|2|3)|ambos|ambas"
    r"|todos|todas|cada\s+uno|cada\s+anillo)\b"
    r"|\bmismo\s+nombre\b|\blos\s+(?:dos|tres)\s+(?:con|igual)\b",
    re.I,
)
#: «una lila y la otra fucsia», «uno rosa y el otro azul»: un color por anillo.
_UNO_Y_OTRO = re.compile(
    r"\b(?:un[ao]?|el\s+primer[o]?|la\s+primera)\b.*\b(?:y|e)\s+(?:la|el)\s+otr[oa]\b",
    re.I,
)


def cantidad_de_todos(texto: str | None) -> int | None:
    """«Los dos de una huellita» -> 1 (para TODOS los anillos). None si no lo dice."""
    m = _CANTIDAD_DE_TODOS.search(_sin_tildes(texto or ""))
    return _VALOR_DE_CANTIDAD.get(m.group(1).lower()) if m else None


def poner_cantidad_a_todos(b: Borrador, cantidad: int) -> list[int]:
    """La cantidad a los anillos que no la tienen. Devuelve cuáles (04/10:
    «los dos de una huellita» quedaba solo en el primero y al segundo se le
    volvía a preguntar)."""
    puestos = []
    for i in range(b.anillos_total):
        v = b.vista(i)
        if v.es_cadena or v.cantidad is not None:
            continue
        v.cantidad = cantidad
        b.poner_anillo(i, v)
        puestos.append(i)
    return puestos


def grabado_para_todos(texto: str | None) -> bool:
    """¿Dijo que el grabado va en todos los anillos («en los dos, Khalifa»)?"""
    return bool(_GRABADO_DE_TODOS.search(_sin_tildes(texto or "")))


def poner_grabado_a_todos(b: Borrador, grabado: list[str]) -> list[int]:
    """El grabado a los anillos que no lo tienen. Devuelve cuáles."""
    puestos = []
    for i in range(b.anillos_total):
        v = b.vista(i)
        if v.es_cadena or v.grabado or v.sin_grabado:
            continue
        v.grabado = list(grabado)
        b.poner_anillo(i, v)
        puestos.append(i)
    return puestos


def colores_por_anillo(b: Borrador, texto: str | None) -> list[tuple[int, object]]:
    """«Una lila y la otra fucsia» con varios anillos de UNA huellita: un color
    entero por anillo, en orden, a los que no tienen colores. Si no cuadra
    (otra cantidad, más o menos colores), nada: decide el modelo."""
    from app.domain.colores_texto import leer_varias

    if not b.varios or not _UNO_Y_OTRO.search(_sin_tildes(texto or "")):
        return []
    vistas = b.vistas()
    anillos = [i for i, v in enumerate(vistas) if not v.es_cadena and v.cantidad == 1]
    lectura = leer_varias(texto or "")
    colores = [c for c, d in lectura.parejas if c == d] if lectura.parejas else []
    colores = colores or list(lectura.sueltos)
    if len(anillos) < 2 or len(colores) != len(anillos):
        return []
    # El primero puede haberlo anotado ya el modelo en este turno: solo a los
    # que no tienen.
    return [
        (i, c) for i, c in zip(anillos, colores, strict=True) if not vistas[i].huellitas
    ]


def poner_colores(b: Borrador, asignados: list[tuple[int, object]]) -> None:
    """Cada anillo con su huellita entera del color que dijo."""
    for i, color in asignados:
        v = b.vista(i)
        v.huellitas = [HuellitaDelBorrador(corazon=color, dedos=color)]
        b.poner_anillo(i, v)


def poner_tallas(b: Borrador, asignadas: list[tuple[int, float]]) -> None:
    """Las tallas que ella DIJO, cada una en su anillo: quedan listas (04/10)."""
    for i, talla in asignadas:
        v = b.vista(i)
        v.talla, v.talla_revisar, v.talla_confirmada = talla, False, True
        v.talla_rango = v.talla_motivo = ""
        b.poner_anillo(i, v)


def anillo_del_mensaje(
    b: Borrador,
    texto: str | None,
    cambios: CambiosDelBorrador,
    *,
    foto_de_talla: bool = False,
    nuevos: int = 0,
) -> int | None:
    """¿Lo que dijo es de OTRO anillo que el que va? Su número (desde 0) o None.

    Las clientas no hablan «del anillo actual»: dicen «talla 6 el de una»,
    «para el de tres: …», o mandan la foto de la regla del que no sabían. El
    bot pregunta en orden, de a uno; pero lo que ella adelanta de otro anillo
    se guarda en ESE (ensayo del 02/10: la foto de la regla del de 3 le pisó la
    talla 6 al de 1, y los nombres del de 3 quedaron en el de 1).
    """
    if not b.varios:
        return None
    del_anillo = (
        cambios.cantidad_huellitas is not None
        or cambios.huellitas
        or cambios.grabado is not None
        or cambios.sin_grabado
        or cambios.talla is not None
        or cambios.medida_cm is not None
        or foto_de_talla
    )
    if not del_anillo:
        return None
    actual = len(b.anillos)
    limpio = _sin_tildes(texto or "")
    vistas = b.vistas()
    elegido: int | None = None
    if (n := _huellitas_de(_EL_DE.search(limpio))) is not None:
        con_esas = [
            i for i, v in enumerate(vistas) if v.cantidad == n and not v.es_cadena
        ]
        if len(con_esas) == 1:
            elegido = con_esas[0]
    de_anillo = (
        cambios.talla is not None
        or cambios.medida_cm is not None
        or (cambios.cantidad_huellitas or 1) > 1
        or foto_de_talla
    )
    if elegido is None and habla_de_cadena(limpio) and not de_anillo:
        # «Para la cadena: rosada y con el nombre Luna».
        cadenas = [i for i, v in enumerate(vistas) if v.es_cadena]
        if len(cadenas) == 1:
            elegido = cadenas[0]
    if elegido is None and (m := _ORDINAL.search(limpio)):
        posicion = _POSICION[m.group(1).lower()]
        if posicion < len(vistas):
            elegido = posicion
    if (
        elegido is None
        and nuevos
        and b.cantidad is not None
        and cambios.cantidad_huellitas is None
        and re.search(r"\b(otro|otra)\b", limpio, re.I)
    ):
        # «Y otro de 1, rojo» con el que va ya empezado: es del que acaba de
        # nacer. Si trae una cantidad, esa es del que va (`contar_anillos`).
        elegido = len(vistas) - 1
    if (
        elegido is None
        and (foto_de_talla or cambios.medida_cm is not None)
        and _tiene_talla(vistas[actual])
    ):
        # La foto de la regla sin decir de cuál: si el que va ya tiene talla,
        # es la del primero que todavía no la tiene.
        elegido = next(
            (
                i
                for i, v in enumerate(vistas)
                if i != actual and not v.es_cadena and not _tiene_talla(v)
            ),
            None,
        )
    if elegido is None and sum(1 for v in vistas if not v.es_cadena) == 2:
        # «El mío dice Rocky» / «el de ella dice Kira»: con DOS anillos, «el
        # mío» es el primero y «el de ella», «el de mi hermana», «el otro» el
        # segundo. Prueba de verdad (04/10): «el de ella dice Kira» pisó el
        # Rocky del primero y el resumen salió con Kira en los dos.
        suyo, mio = bool(_EL_SUYO.search(limpio)), bool(_EL_MIO.search(limpio))
        if suyo and not mio:
            elegido = 1
        elif mio and not suyo:
            elegido = 0
    return None if elegido == actual else elegido


#: «el de ella», «el de mi hermana», «la de tu mamá», «el otro», «para ella».
_EL_SUYO = re.compile(
    r"\b(?:el|la)\s+de\s+(?:ella|el|mi\s+\w+|tu\s+\w+|su\s+\w+)\b"
    r"|\b(?:el|la)\s+otr[oa]\b"
    r"|\bpara\s+(?:ella|mi\s+(?:hermana|mama|amiga|novia|novio|esposo|esposa|hija"
    r"|hijo|tia|abuela|prima|suegra|mejor\s+amiga))\b",
    re.I,
)
#: «el mío», «la mía», «para mí» (al final de la frase).
_EL_MIO = re.compile(r"\b(?:el|la)\s+mi[oa]\b|\bpara\s+mi\s*(?:[.,!]|$)", re.I)


# ---------------------------------------------------------------------------
# La cadena (03/10): solo si ella pregunta
# ---------------------------------------------------------------------------

#: Palabras con las que pregunta por la cadena.
#: «Dije» el colgante, no «te DIJE que no» (10/10: a «porque te dije que no me
#: gusta la plata» le llegó la información de la cadena).
_HABLA_DE_CADENA = re.compile(
    r"\b(cadenas?|cadenitas?|collar(es)?|dijes|colgantes?|gargantillas?)\b"
    r"|\b(?:un|el|del|al|los|unos|ese|este)\s+dije\b(?!\s+que\b)",
    re.I,
)
#: Pregunta por más productos del portafolio (y entonces sí se le muestra).
_PIDE_MAS_PRODUCTOS = re.compile(
    r"\b(otros?|otras?|mas|demas)\s+(productos?|opciones|modelos|cosas|articulos|"
    r"joyas|accesorios|disenos|referencias)\b"
    # «el que más venden» es el más vendido, no «¿qué más venden?» (17/10).
    r"|(?<!\bel\s)(?<!\bla\s)(?<!\blo\s)(?<!\blos\s)"
    r"\bque\s+(mas|otra\s+cosa|otros?\s+\w+)\s+(tienen|venden|hay|manejan|hacen|ofrecen)\b"
    r"|\b(tienen|venden|hacen|manejan)\s+(algo\s+mas|mas\s+cosas|otra\s+cosa)\b"
    r"|\bsolo\s+(tienen|venden|hacen|manejan)\s+anillos\b"
    r"|\b(catalogo|portafolio)\b",
    re.I,
)
#: «Mejor la cadena» (en vez del anillo), no «y también una cadena».
_CAMBIA_A_CADENA = re.compile(r"\b(mejor|en\s+vez|en\s+lugar|cambi\w*|ya\s+no)\b", re.I)

# ---------------------------------------------------------------------------
# El anillo de corazón (17/10): sí se ofrece, desde el primer mensaje
# ---------------------------------------------------------------------------

#: Que habla del ANILLO de corazón. Ojo: «el corazón rosado y los deditos
#: blancos» es la huellita (su piedra grande también se llama corazón). Por eso
#: no basta la palabra: «anillo de corazón», «el de corazón», «de promesa», o
#: como lo dijo Martha (17/10): «otro que no es de huellita, solamente con la
#: piedrita».
_HABLA_DEL_CORAZON = re.compile(
    r"\banillos?\s+(?:de|con)\s+(?:un\s+|el\s+)?corazon\w*"
    r"|\b(?:el|la|del|uno|otro|al|ese|este)\s+de\s+(?:el\s+|un\s+)?corazon\w*"
    r"|\banillos?\s+de\s+(?:promesa|compromiso)\b"
    r"|\bsin\s+(?:la\s+)?huell\w*"
    r"|\bno\s+(?:es|tiene|lleva)\s+(?:de\s+|la\s+)?huell\w*"
    r"|\b(?:solo|solamente|nada\s+mas)\s+(?:con\s+)?(?:la\s+|una\s+)?piedr\w*",
    re.I,
)
#: «Mejor el de huellitas», «prefiero con huellita»: deja el corazón.
_VUELVE_A_HUELLITAS = re.compile(
    r"\b(?:mejor|prefiero|cambi\w*|en\s+vez|en\s+lugar)\b[^.?!]{0,30}\bhuell", re.I
)


def habla_del_corazon(texto: str | None) -> bool:
    """¿Habla del anillo de corazón (no del corazón de una huellita)?"""
    return bool(_HABLA_DEL_CORAZON.search(_sin_tildes(texto or "")))


_TAMBIEN = re.compile(r"\b(tambien|ademas|otra|y\s+una)\b", re.I)


def habla_de_cadena(texto: str | None) -> bool:
    return bool(_HABLA_DE_CADENA.search(_sin_tildes(texto or "")))


#: «la cadena con 2 huellitas?», «cadena de dos huellas», «puede llevar varias
#: huellitas la cadena?». La cadena lleva UNA (`HUELLITAS_DE_LA_CADENA`).
_VARIAS_HUELLITAS = re.compile(
    r"\b(?:2|3|4|dos|tres|cuatro|varias|mas\s+de\s+una|otra)\s+"
    r"(?:huellit\w*|huell\w*|patit\w*|mascot\w*|perrit\w*|gatit\w*)",
    re.I,
)


def pide_cadena_con_varias(texto: str | None) -> bool:
    """¿Quiere (o pregunta por) la cadena con más de una huellita?"""
    limpio = _sin_tildes(texto or "")
    return bool(_HABLA_DE_CADENA.search(limpio) and _VARIAS_HUELLITAS.search(limpio))


#: El bot prometiendo escribirle después o «programar un recordatorio» (09/10).
#: Si ella lo deja para otro momento, se agradece y se cierra: nada de promesas
#: ni de acciones inventadas, salvo que ELLA pida que le escriban.
_PROMETE_ESCRIBIR = re.compile(
    r"\b(?:te|le)\s+(?:escribo|escribire|vuelvo\s+a\s+escribir|recuerdo|recordare"
    r"|contacto|contactare|busco|buscare|aviso|avisare|hablo|hablare)\b"
    r"[^.!?\n]*\b(?:mes|quincena|semana|dias|luego|despues|mas\s+adelante|manana"
    r"|pronto|ese\s+dia)\b"
    r"|\b(?:recordatorio|agend\w+|program\w+\s+(?:un\s+)?(?:aviso|mensaje))\b",
    re.I,
)


def sin_promesas_de_escribir(texto: str) -> str:
    """Quita las frases donde el bot promete escribirle más adelante."""
    if not texto:
        return texto
    lineas = []
    for linea in texto.split("\n"):
        frases = [
            f
            for f in re.split(r"(?<=[.!?])\s+", linea)
            if not _PROMETE_ESCRIBIR.search(_sin_tildes(f))
        ]
        if frases or not linea.strip():
            lineas.append(" ".join(frases))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


# ════════════════════════════════════════════════════════════════════════════
# NO ACOSAR (Camilo, 09/10)
# ════════════════════════════════════════════════════════════════════════════
# Real (Yulieth): «No la medida te las confirmo en la tarde pero sería uno más
# grande que el otro». El bot se la volvió a pedir cuatro veces, y no siempre
# con «¿?»: «Me falta la medida del primer anillo; cuando puedas, mándame la
# foto con la regla». Las reglas:
#   · lo que ella dice que manda DESPUÉS no se le pide más en la charla; le
#     llega UN recordatorio sobre eso y ya;
#   · lo que no contesta se le pide UNA vez más; después, el recordatorio.

#: Cuántas veces se le pide algo que no da antes de dejarlo al recordatorio.
VECES_QUE_SE_PIDE = 2

#: De qué habla una frase (para saber QUÉ se le está pidiendo).
_DE_QUE: dict[str, re.Pattern] = {
    "talla": re.compile(r"\b(?:tallas?|medidas?|regla|med[ií]\w*|mid[eoaí]\w*)\b", re.I),
    "cantidad de huellitas": re.compile(
        r"cu[aá]ntas\s+huellitas|\b1\s*,\s*2\s*o\s*3\b|\bde\s+1\s+o\s+(?:de\s+)?2\b",
        re.I,
    ),
    "colores": re.compile(r"\bcolor(?:es)?\b|\btonos?\b", re.I),
    "grabado": re.compile(
        r"\bgrab(?:ar|amos|ado|arle|emos|ados)\b"
        r"|\bnombres?\s+(?:quieres|te\s+gustar\w*|va|van|lleva)\b",
        re.I,
    ),
    "nombre completo": re.compile(r"a\s+nombre\s+de\s+qui[eé]n|nombre\s+completo", re.I),
}
#: Que la frase PIDE algo (no que solo lo nombra): una pregunta, «mándame»,
#: «cuando puedas», «me falta»…
_PIDE_ALGO = re.compile(
    r"\?|\bm[aá]nd(?:a|ame|amela|amelas|amelo|ar)\b|\benv[ií](?:a|ame|ar)\b"
    r"|\bcomp[aá]rt(?:e|eme|ir)\b|\bp[aá]s(?:a|ame|ar)\b|\bregal(?:a|as|ame)\b"
    r"|\bcuando\s+(?:puedas|tengas|la\s+tengas|las\s+tengas)\b|\bme\s+falta\b"
    r"|\bfalta\b|\bnecesito\b|\bme\s+(?:dices|cuentas|confirmas|escribes)\b",
    re.I,
)
#: «Te la confirmo en la tarde», «después te mando la medida», «cuando la
#: mida», «todavía no la tengo». «Te confirmo QUE es rosa» no es dejarlo después.
_LO_DA_DESPUES = re.compile(
    r"\bte\s+(?:l[ao]s?\s+)?(?:confirmo|digo|mando|paso|envio|aviso|escribo|cuento)\b"
    r"(?!\s+que\b)"
    r"|\ben\s+la\s+(?:tarde|noche|manana)\b|\bmas\s+tarde\b|\bluego\b|\bdespues\b"
    r"|\bahorita\s+(?:no|l[ao]s?\b)|\bcuando\s+(?:l[ao]s?\s+)?(?:mida|tenga|llegue|pueda)\b"
    r"|\bmanana\b|\ben\s+un\s+rat\w*\b|\btodavia\s+no\b|\baun\s+no\b|\bdejame\s+(?:ver|mirar|medir)",
    re.I,
)


#: Dónde termina una frase: en «. ! ?», o en un emoji seguido de mayúscula, que
#: es como escribe el bot («… para el segundo 🫶 Cuando tengas…»).
_FIN_DE_FRASE = re.compile(
    r"(?<=[.!?])\s+|(?<=[^\w\s,;:¿¡«»\"'()\-])\s+(?=[¿¡A-ZÁÉÍÓÚÑ])"
)


def _frases(texto: str) -> list[str]:
    return [
        f
        for linea in (texto or "").split("\n")
        for f in _FIN_DE_FRASE.split(linea)
        if f.strip()
    ]


def pide(texto: str, que: str) -> bool:
    """¿Alguna frase del mensaje le PIDE `que` («talla», «colores»…)?"""
    patron = _DE_QUE.get(que)
    if patron is None:
        return False
    return any(patron.search(f) and _PIDE_ALGO.search(f) for f in _frases(texto))


_LA_FOTO = re.compile(r"\bfotos?\b|\bfotico\b", re.I)
_OTRA_FOTO = re.compile(
    r"\b(?:comprobante|pago|transferencia|consignacion|abono|perr\w*|gat\w*|mascota)\b",
    re.I,
)


def lo_deja_para_despues(texto: str | None, ultimo_del_bot: str = "") -> list[str]:
    """Lo que ella dice que da DESPUÉS: lo que nombra («la medida te la confirmo
    en la tarde»), o, si no nombra nada, lo que le acababan de pedir («te
    confirmo en la tarde» a «¿me mandas la foto de la regla?»)."""
    limpio = _sin_tildes(texto or "")
    if not _LO_DA_DESPUES.search(limpio):
        return []
    # «Le pido la foto a ella y ya te la mando» (13/10, prueba): la foto que
    # manda después es la de la medida, no lo último que se le preguntó (su
    # nombre). Salvo que sea la de un pago o la de su mascota.
    if _LA_FOTO.search(limpio) and not _OTRA_FOTO.search(limpio):
        return ["talla"]
    nombra = [q for q, p in _DE_QUE.items() if p.search(limpio)]
    if nombra:
        return nombra
    return [q for q in _DE_QUE if pide(ultimo_del_bot, q)]


def habla_de(texto: str | None, que: str) -> bool:
    patron = _DE_QUE.get(que)
    return bool(patron and patron.search(_sin_tildes(texto or "")))


def que_no_se_pide(b: Borrador) -> set[str]:
    """Lo que NO se le pide ahora: lo que manda después, lo ya pedido de más y
    lo que ya está anotado (Yulieth: una reescritura le volvió a preguntar el
    color que ya tenía)."""
    # Ya pagó (12/10): lo que falta es para pasar su pedido al taller, se le
    # pide aunque ya se le haya pedido (no es insistir para venderle). Lo que
    # dijo que manda después, igual se respeta.
    pago = b.pagado_sin_pedido or b.abono_reportado
    return (
        set(b.lo_manda_despues)
        | (
            set()
            if pago
            else {q for q, n in b.veces_pedido.items() if n >= VECES_QUE_SE_PIDE}
        )
        | (set(_DE_QUE) - lo_que_le_falta(b))
    )


def queda_algo_del_anillo(b: Borrador, siguiente: str) -> bool:
    """«describir el anillo 2 de 2»: ¿a ESE anillo le falta algo que SÍ se le
    pueda pedir? Si solo le falta lo bloqueado (la talla que manda en la
    tarde), no se le dice «vamos con el siguiente anillo» (Yulieth, 09/10)."""
    m = re.search(r"(\d+)\s+de\s+\d+", siguiente)
    if not m:
        return True
    i = int(m.group(1)) - 1
    if not 0 <= i < b.anillos_total:
        return True
    return bool(set(b.vista(i).falta_del_anillo()) - que_no_se_pide(b))


def otro_anillo_vacio(b: Borrador, siguiente: str) -> bool:
    """¿El anillo que sigue está por empezar (sin cantidad)?"""
    m = re.search(r"(\d+)\s+de\s+\d+", siguiente)
    if not m:
        return True
    i = int(m.group(1)) - 1
    return 0 <= i < b.anillos_total and b.vista(i).cantidad is None


def sin_pedir(texto: str, que: set[str]) -> str:
    """El mensaje sin las frases que le PIDEN algo de `que` (con o sin «¿?»)."""
    if not texto or not que:
        return texto
    patrones = [_DE_QUE[q] for q in que if q in _DE_QUE]
    lineas = []
    for linea in texto.split("\n"):
        frases = [
            f
            for f in _FIN_DE_FRASE.split(linea)
            if not (_PIDE_ALGO.search(f) and any(p.search(f) for p in patrones))
        ]
        if frases or not linea.strip():
            lineas.append(" ".join(frases))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


def lo_que_le_falta(b: Borrador) -> set[str]:
    """Lo que le falta a ELLA, de TODOS los anillos (la talla del primero puede
    faltar mientras se arma el segundo) y su nombre."""
    falta = set(b.falta_de_quien())
    for v in b.vistas():
        falta |= set(v.falta_del_anillo())
    return falta


#: Lo SEPARA con el abono (13/10): el botón «💍 Quiero separarlo» o decirlo
#: («lo separo», «resérvamelo», «apártamelo»). «No lo quiero separar» no.
_QUIERE_SEPARAR = re.compile(
    r"\bsepar(?:ar|arlo|arla|o|a|amelo|emoslo)\b|\breserv(?:ar|arlo|amelo|alo)\b"
    r"|\bapart(?:ar|arlo|amelo|alo)\b",
    re.I,
)
_NO_SEPARAR = re.compile(r"\bno\s+(?:\w+\s+){0,2}(?:separ|reserv|apart)", re.I)
#: Lo que el bot ofreció: separarlo con el abono y la talla después.
_OFRECIO_SEPARAR = re.compile(r"separ\w*\s+con\s+el\s+abono", re.I)
_ACEPTA = re.compile(
    r"^\W*(?:si+|claro|dale|listo|de\s+una|ok|okey|bueno|perfecto|me\s+parece|vale"
    r"|hagamoslo|hagale|por\s+favor|porfa)\b",
    re.I,
)


def quiere_separar(texto: str | None) -> bool:
    limpio = _sin_tildes(texto or "")
    return bool(_QUIERE_SEPARAR.search(limpio)) and not _NO_SEPARAR.search(limpio)


def acepta_separar(texto: str | None, ultimo_del_bot: str) -> bool:
    """«Sí» a «¿lo separas con el abono y la talla después?»."""
    return bool(
        _OFRECIO_SEPARAR.search(_sin_tildes(ultimo_del_bot or ""))
        and _ACEPTA.search(_sin_tildes(texto or ""))
    )


def al_dia_lo_que_se_pide(
    b: Borrador, texto_de_ella: str | None, ultimo_del_bot: str
) -> None:
    """ANTES de contestar: lo que dejó para después, y lo que ya no hace falta."""
    # Lo separa con el abono y la talla después (Camilo, 13/10).
    if (
        b.talla is None
        and not b.es_cadena
        and (
            quiere_separar(texto_de_ella) or acepta_separar(texto_de_ella, ultimo_del_bot)
        )
    ):
        b.talla_despues = True
    falta = lo_que_le_falta(b)
    despues = lo_deja_para_despues(texto_de_ella, ultimo_del_bot)
    for que in despues:
        if que in falta:
            b.lo_manda_despues[que] = b.turnos
    for que in list(b.lo_manda_despues):
        # Lo dio, o volvió a hablar de eso (no para dejarlo después): se suelta.
        if que not in falta or (que not in despues and habla_de(texto_de_ella, que)):
            del b.lo_manda_despues[que]
            if que in b.recordado_despues:
                b.recordado_despues.remove(que)
    for que in list(b.veces_pedido):
        if que not in falta or habla_de(texto_de_ella, que):
            del b.veces_pedido[que]


def contar_lo_pedido(b: Borrador, enviado: str) -> None:
    """DESPUÉS de contestar: cada cosa que le faltaba y se le pidió, cuenta."""
    for que in lo_que_le_falta(b):
        if que in _DE_QUE and pide(enviado, que):
            b.veces_pedido[que] = b.veces_pedido.get(que, 0) + 1


def pregunta_por_cadenas(texto: str | None) -> bool:
    """¿Preguntó por cadenas o por más productos? Solo entonces se le muestran
    (Camilo, 03/10: la cadena NUNCA se ofrece por cuenta propia)."""
    limpio = _sin_tildes(texto or "")
    return bool(_HABLA_DE_CADENA.search(limpio) or _PIDE_MAS_PRODUCTOS.search(limpio))


def quitar_cadena_no_pedida(texto: str) -> tuple[str, bool]:
    """Las frases que nombran la cadena, fuera: ella no ha preguntado por ella.

    La red de seguridad de la regla de Camilo (03/10): aunque el modelo la
    ofrezca, a la clienta no le llega. Devuelve (el texto, si quitó algo)."""
    if not texto or not habla_de_cadena(texto):
        return texto, False
    lineas = []
    for linea in texto.split("\n"):
        frases = re.split(r"(?<=[.!?…])\s+", linea)
        lineas.append(" ".join(f for f in frases if not habla_de_cadena(f)).strip())
    return "\n".join(lineas).strip(), True


def _vacio(v: Borrador) -> bool:
    return (
        v.cantidad is None
        and not v.huellitas
        and not v.grabado
        and v.talla is None
        and not (v.talla_fotos or v.talla_escrita)
    )


def _anotar_la_pieza(b: Borrador, limpio: str, nuevos: int, pieza: str) -> int:
    """La pieza que es la cadena (o el anillo de corazón): la nueva de este
    turno, la que va si está vacía (o si dice «mejor la cadena»), una por
    empezar vacía, o una nueva («y también una cadena»). Devuelve cuántas
    piezas se sumaron."""
    vistas = b.vistas()
    otra = (
        r"\b(otra|dos|2)\s+cadenas?\b"
        if pieza == CADENA
        else r"\b(otro|dos|2)\s+(?:anillos?\s+)?de\s+corazon"
    )
    if (
        any(v.pieza == pieza for v in vistas)
        and not nuevos
        and not re.search(otra, limpio)
    ):
        return 0  # ya está anotada: el modelo la repite
    actual = len(b.anillos)
    agregadas = 0
    if nuevos:
        i = b.anillos_total - 1
    elif _vacio(vistas[actual]) or (
        _CAMBIA_A_CADENA.search(limpio) and not _TAMBIEN.search(limpio)
    ):
        i = actual
    elif (
        vacia := next((k for k, v in enumerate(vistas) if _vacio(v)), None)
    ) is not None:
        i = vacia
    else:
        if b.anillos_total >= MAX_ANILLOS:
            return 0
        b.agregar_anillo()
        i = b.anillos_total - 1
        agregadas = 1
    v = b.vista(i)
    if pieza == CORAZON:
        # Es un anillo: la talla y el grabado que ya dio se quedan.
        v.pieza, v.cantidad = CORAZON, PIEDRAS_DEL_CORAZON
        v.huellitas = v.huellitas[:PIEDRAS_DEL_CORAZON]
        for h in v.huellitas:
            h.dedos, h.dedos_alternos = h.corazon, []
        b.poner_anillo(i, v)
        return agregadas
    v.pieza, v.cantidad = CADENA, HUELLITAS_DE_LA_CADENA
    v.huellitas = v.huellitas[:HUELLITAS_DE_LA_CADENA]
    v.sin_grabado = False
    for campo in CAMPOS_DE_LA_TALLA:
        setattr(
            v, campo, Borrador.model_fields[campo].get_default(call_default_factory=True)
        )
    b.poner_anillo(i, v)
    return agregadas


class HuellitaPropuesta(BaseModel):
    numero: int = Field(description="1, 2 o 3: qué huellita del anillo")
    corazon: ColorCircon | None = None
    dedos: ColorCircon | None = None
    dedos_alternos: list[ColorCircon] = Field(
        default_factory=list,
        description="Solo si los 4 deditos NO van del mismo color: los 4, en orden",
    )
    mascota: str = Field(default="", description="De qué mascota es, si lo dijo")


class CambiosDelBorrador(BaseModel):
    """Solo lo que ESTE mensaje cambia. Lo que no se toca va en null / vacío."""

    cantidad_huellitas: int | None = None
    huellitas: list[HuellitaPropuesta] = Field(default_factory=list)
    grabado: list[str] | None = Field(
        default=None,
        description=(
            "La lista COMPLETA de renglones a grabar si cambió (nombres de las "
            "mascotas con sus símbolos o fechas). Nunca el nombre de la clienta."
        ),
    )
    sin_grabado: bool | None = None
    talla: float | None = None
    medida_cm: float | None = Field(
        default=None, description="Diámetro interno que ESCRIBIÓ la clienta, en cm"
    )
    nombre_clienta: str | None = None
    ciudad: str | None = None
    direccion: str | None = Field(
        default=None,
        description="Dirección de entrega COMPLETA como la escribió (calle, número, "
        "barrio, apto). Sin la ciudad.",
    )
    cedula: str | None = Field(
        default=None,
        description="La cédula para la guía, solo los números, como la escribió",
    )
    celular: str | None = Field(
        default=None,
        description="El celular de contacto PARA LA GUÍA (puede no ser el de "
        "WhatsApp). Solo los números",
    )
    recoge_en_tienda: bool | None = Field(
        default=None,
        description="true si dice que lo RECOGE en Floridablanca en vez de envío; "
        "false si cambia a envío",
    )
    fecha_deseada: str | None = None


#: Cuántos diseños se le pueden enseñar de una vez. Más es una ráfaga de
#: fotos que nadie mira.
MAXIMO_VISTAS = 3


class DisenoParaVer(BaseModel):
    """Un diseño que la clienta quiere VER, sin que quede escogido.

    «Muéstrame cómo queda en rosado» no es «lo quiero rosado»: está mirando.
    Guardarlo sería decidir por ella; no enseñárselo es perder la venta.
    """

    nombre: str = Field(
        default="",
        description="Cómo se llama esta opción, para el pie de foto: "
        '"Todo rosado", "Corazón rosado y deditos rojos"',
    )
    huellitas: list[HuellitaPropuesta] = Field(
        default_factory=list,
        description="Las huellitas de ESTE diseño, completas (corazón y dedos)",
    )


class Jugada(BaseModel):
    lectura: str = Field(description="En una frase: qué quiso decir la clienta")
    cambios: CambiosDelBorrador
    acciones: list[AccionAsesora] = Field(default_factory=list)
    mensaje: str = Field(description="Lo que se le responde, como escribe Lía")
    mensaje_final: str = Field(
        default="",
        description=(
            "Opcional: lo que va DESPUÉS de las fichas, fotos o cuentas que manda "
            "el sistema (p. ej. la pregunta siguiente). Vacío si no hace falta."
        ),
    )
    vistas_previas: list[DisenoParaVer] = Field(
        default_factory=list,
        description="Con la acción MOSTRAR_COMO_QUEDA: los diseños que quiere "
        "VER sin escogerlos todavía. Si pide comparar dos («uno rosado y otro "
        "rojo»), van los dos. Máximo 3.",
    )
    confianza: Confianza
    nota_para_lia: str = ""


class MensajeReescrito(BaseModel):
    """Solo el texto, cuando el primero no se podía mandar (falso o repetido)."""

    mensaje: str = Field(description="El mensaje nuevo, corto, como escribe Lía")


# ══════════════════════════════════════════════════════════════════════════
#  APLICAR: el modelo propone, Python valida
# ══════════════════════════════════════════════════════════════════════════


def _palabras(texto: str) -> set[str]:
    sin_tildes = unicodedata.normalize("NFKD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return set(re.sub(r"[^a-z0-9 ]", " ", sin_tildes.lower()).split())


def aplicar(
    borrador: Borrador, cambios: CambiosDelBorrador
) -> tuple[Borrador, list[str]]:
    """Aplica lo que el modelo propone. Devuelve el borrador y lo que NO pasó.

    Lo rechazado vuelve al modelo en el turno siguiente, para que pregunte en
    vez de dar por hecho algo que no quedó guardado.
    """
    b = borrador.model_copy(deep=True)
    rechazos: list[str] = []

    if b.es_cadena:
        # La cadena (03/10): una huellita, sin talla y siempre con nombre.
        quitar: dict = {}
        if cambios.cantidad_huellitas not in (None, HUELLITAS_DE_LA_CADENA):
            rechazos.append("la cadena lleva UNA sola huellita (corazón + 4 deditos)")
        if cambios.talla is not None or cambios.medida_cm is not None:
            rechazos.append("la cadena no lleva talla: no se anotó")
            quitar.update(talla=None, medida_cm=None)
        if cambios.sin_grabado:
            rechazos.append(
                "la cadena SIEMPRE lleva el nombre grabado: pregúntale cuál (hasta 2 "
                "por lado)"
            )
            quitar["sin_grabado"] = None
        cambios = cambios.model_copy(update={"cantidad_huellitas": None, **quitar})
        b.cantidad = HUELLITAS_DE_LA_CADENA
    elif b.es_corazon:
        # El anillo de corazón (17/10): un solo corazón; lo demás, como un anillo.
        if cambios.cantidad_huellitas not in (None, PIEDRAS_DEL_CORAZON):
            rechazos.append(
                "el anillo de corazón lleva UN solo corazón (no huellitas): no se "
                "anotó esa cantidad"
            )
        cambios = cambios.model_copy(update={"cantidad_huellitas": None})
        b.cantidad = PIEDRAS_DEL_CORAZON

    if cambios.cantidad_huellitas is not None:
        if cambios.cantidad_huellitas in (1, 2, 3):
            b.cantidad = cambios.cantidad_huellitas
        else:
            rechazos.append(
                f"cantidad {cambios.cantidad_huellitas} no existe (solo 1, 2 o 3)"
            )

    for p in cambios.huellitas:
        tope = b.cantidad or 3
        if not 1 <= p.numero <= tope:
            donde = (
                "la cadena"
                if b.es_cadena
                else "el anillo de corazón (un solo corazón)"
                if b.es_corazon
                else f"un anillo de {tope}"
            )
            rechazos.append(f"huellita {p.numero} no existe en {donde}")
            continue
        while len(b.huellitas) < p.numero:
            b.huellitas.append(HuellitaDelBorrador())
        h = b.huellitas[p.numero - 1]
        if p.corazon is not None:
            h.corazon = p.corazon
        if len(p.dedos_alternos) == 4:
            h.dedos_alternos = list(p.dedos_alternos)
            h.dedos = None
        elif p.dedos_alternos:
            rechazos.append("dedos alternos necesitan exactamente 4 colores")
        if p.dedos is not None:
            h.dedos = p.dedos
            h.dedos_alternos = []
        if p.mascota.strip():
            h.mascota = p.mascota.strip()[:30]
        if b.es_corazon:
            # Una sola piedra: venga como «corazón» o como «dedos», es SU color.
            color = p.corazon or p.dedos or h.corazon
            h.corazon = h.dedos = color
            h.dedos_alternos = []

    if cambios.nombre_clienta and cambios.nombre_clienta.strip():
        b.nombre_clienta = cambios.nombre_clienta.strip()[:80]
    if cambios.ciudad and cambios.ciudad.strip():
        b.ciudad = cambios.ciudad.strip()[:60]
    if cambios.cedula and cambios.cedula.strip():
        # Solo los dígitos: llega como «CC 1.007.977.466» o «cc: 1007977466».
        solo_numeros = re.sub(r"\D", "", cambios.cedula)
        if 6 <= len(solo_numeros) <= 12:
            b.cedula = solo_numeros
        else:
            rechazos.append(
                f"«{cambios.cedula}» no parece una cédula: vuelve a pedírsela"
            )
    if cambios.celular and cambios.celular.strip():
        solo_numeros = re.sub(r"\D", "", cambios.celular)
        # Un celular colombiano tiene 10 dígitos; con el 57 delante, 12.
        if len(solo_numeros) in (10, 12):
            b.celular = solo_numeros[-10:]
        else:
            rechazos.append(f"«{cambios.celular}» no parece un celular de 10 dígitos")
    if cambios.recoge_en_tienda is not None:
        b.recoge = bool(cambios.recoge_en_tienda)
        if b.recoge:
            # Si lo recoge no hay envío que pagar, ni antes ni al recibir.
            b.envio_con_saldo = False
    if cambios.direccion and cambios.direccion.strip():
        direccion = " ".join(cambios.direccion.split())[:120]
        if re.search(r"\d", direccion):
            b.direccion = direccion
            b.recoge = False
        else:
            # «Mi casa», «el barrio San Luis»: una guía no se hace con eso.
            rechazos.append(
                f"«{direccion}» no parece una dirección completa (le falta el "
                "número): pídele calle y número"
            )
    if cambios.fecha_deseada and cambios.fecha_deseada.strip():
        b.fecha_deseada = cambios.fecha_deseada.strip()[:40]
        _nota(b, f"Necesita el anillo para: {b.fecha_deseada}")

    if cambios.grabado is not None:
        grabado, problemas = _validar_grabado(cambios.grabado, b.nombre_clienta)
        if b.es_cadena and grabado:
            grabado, de_la_cadena = lados_de_la_cadena(grabado)
            problemas += de_la_cadena
            if not grabado:
                # No cabía: se deja lo que había (no se borra por un intento).
                grabado = list(b.grabado)
        rechazos.extend(problemas)
        if grabado or not cambios.grabado:
            b.grabado = grabado
            if grabado:
                b.sin_grabado = False
    if cambios.sin_grabado:
        b.sin_grabado = True
        b.grabado = []

    if cambios.talla is not None and 1.2 <= float(cambios.talla) <= 2.6:
        # «1,8» no es una talla: es la medida en cm de la foto de la regla. Pasó
        # el 19/09 con una clienta y la talla se perdió: el modelo la puso en
        # `talla` y Python la rechazó («no existe en el mandril»).
        cambios = cambios.model_copy(
            update={"talla": None, "medida_cm": float(cambios.talla)}
        )
    if cambios.talla is not None:
        if float(cambios.talla) in DIAMETRO_MM:
            # Camilo (04/10): «si dan la talla no hay nada que verificar; eso es
            # solo si mandan la foto del anillo con una regla». La talla que ella
            # DICE queda lista. Pasó el 04/10: escribió «talla seis» y el bot le
            # dijo «en unos minutos te confirmo la talla» y esperó a Lía. Lo que
            # sí espera a Lía: la foto de la regla (si hay una en revisión, un
            # número que repita el modelo no se la salta) y la medida escrita.
            foto_en_revision = b.talla_revisar and bool(b.talla_fotos)
            b.talla = float(cambios.talla)
            b.talla_revisar = foto_en_revision
            if not foto_en_revision:
                b.talla_motivo = b.talla_rango = ""
            b.talla_confirmada = not foto_en_revision
        else:
            rechazos.append(f"la talla {cambios.talla:g} no existe en el mandril")
    elif cambios.medida_cm is not None and b.talla_confirmada:
        # La talla ya está fija (la dijo ella o la confirmó Lía): una estimación
        # no la pisa. Si de verdad midió otra vez, que Lía lo mire.
        _nota(
            b,
            f"Mandó otra medida («{cambios.medida_cm:g}») con la talla ya "
            f"fija ({talla_texto(b.talla)}): revisar",
        )
        rechazos.append(
            f"la talla ya está fija ({talla_texto(b.talla)}): la medida nueva "
            "no la cambia; queda anotada para Lía"
        )
    elif cambios.medida_cm is not None:
        # Una medida ESCRITA es una referencia, nunca una talla confirmada
        # (27/09: «1.8» salió como «¡Es una talla 8!»). Se guarda la más
        # probable para que la conversación siga —nunca se espera a Lía— y Lía
        # la confirma o la corrige desde el panel.
        estimada = estimar(cambios.medida_cm)
        b.talla_escrita = f"{cambios.medida_cm:g}"
        if estimada is not None:
            b.talla = estimada.talla
            b.talla_revisar = True
            b.talla_confirmada = False
            b.talla_rango = estimada.rango
            b.talla_motivo = estimada.para_lia(cambios.medida_cm)
            _nota(b, b.talla_motivo)
        elif b.talla_exige_lia:
            # No se entiende, pero la decide Lía: se le deja anotado y a ella no
            # se le vuelve a preguntar hasta que Lía lo mire.
            b.talla_revisar = True
            b.talla_confirmada = False
            b.talla_motivo = (
                f"Escribió «{cambios.medida_cm:g}» y no se entiende como medida "
                "(ni diámetro ni contorno del dedo): mírala tú"
            )
            _nota(b, b.talla_motivo)
        else:
            rechazos.append(
                f"«{cambios.medida_cm:g}» no se entiende como medida de anillo (ni "
                "diámetro ni contorno del dedo): pregúntale cómo la tomó"
            )

    if b.cantidad is not None and len(b.huellitas) > b.cantidad:
        rechazos.append(
            f"hay {len(b.huellitas)} huellitas con color pero el anillo "
            f"es de {b.cantidad}"
        )
    return b, rechazos


#: Pasó al repasar: «Un gato pantera y una gata calico» terminó grabado como
#: «Gato pantera ♡ Gata calico». Se mira el texto FUERA de paréntesis: «Gordo
#: (carita de gato)» sí es un grabado.
_DESCRIPCION = re.compile(
    r"^(un|una|mi|mis)\s|\b(gat[oa]s?|perr[oa]s?|gatit[oa]s?|perrit[oa]s?|mascotas?|"
    r"panter\w*|calic[oó]|raza|cachorr\w*|criollit[oa]|french|pug|husky|"
    r"schnauzer|labrador|golden|pitbull|chihuahua|siames|persa|angora)\b",
    re.I,
)


def parece_descripcion(renglon: str) -> bool:
    fuera = re.sub(r"\([^)]*\)", " ", renglon)
    partes = [p.strip() for p in re.split(r"[♡❤∞&/,]| y ", fuera) if p.strip()]
    return (
        bool(partes)
        and all(
            _DESCRIPCION.search(_sin_tildes(p)) or not re.search(r"[A-Za-z0-9]", p)
            for p in partes
        )
        and any(_DESCRIPCION.search(_sin_tildes(p)) for p in partes)
    )


def _validar_grabado(
    renglones: list[str], nombre_clienta: str
) -> tuple[list[str], list[str]]:
    problemas: list[str] = []
    limpios = []
    for r in renglones:
        r = " ".join((r or "").split())
        if not r:
            continue
        if not re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]", r) and not re.search(r"[♡❤∞]", r):
            continue
        if parece_descripcion(r):
            problemas.append(
                f"«{r}» describe a la mascota, no es su nombre: no se guardó; "
                "pregúntale cómo se llama"
            )
            continue
        limpios.append(r)
    palabras_clienta = _palabras(nombre_clienta) - {"de", "del", "la", "los"}
    if len(palabras_clienta) >= 2:
        for r in limpios:
            if len(_palabras(r) & palabras_clienta) >= 2:
                problemas.append(
                    f"«{r}» parece el nombre de la clienta, no un grabado: no se guardó"
                )
        limpios = [r for r in limpios if len(_palabras(r) & palabras_clienta) < 2]
    nombres = sum(len(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,}", r)) > 0 for r in limpios)
    if nombres > MAX_NOMBRES:
        problemas.append(f"no caben más de {MAX_NOMBRES} nombres en el aro")
        return [], problemas
    return limpios, problemas


_AFIRMACIONES = {
    "si",
    "sii",
    "siii",
    "si perfecto",
    "perfecto",
    "dale",
    "listo",
    "ok",
    "okis",
    "claro",
    "si claro",
    "si senora",
    "de una",
    "vale",
    "bueno",
    "esa",
    "asi",
    "si asi",
    "si asi esta bien",
    "asi esta bien",
    "super",
    "genial",
}
_OPCIONES_DE_CANTIDAD = re.compile(
    r"\b[123]\s+huellitas?\b.*\bo\b.*\b[123]\s+huellitas?\b|\b1\s*,\s*2\s+o\s+3\b",
    re.I | re.S,
)


def solo_afirma(texto: str | None) -> bool:
    """«Sí», «perfecto», «dale»… sin ningún dato más."""
    limpio = " ".join(re.sub(r"[^a-z ]", " ", _sin_tildes(texto or "").lower()).split())
    return limpio in _AFIRMACIONES


_CANTIDAD_ESCRITA = re.compile(
    r"\b(1|2|3|una|uno|dos|tres|sola|solo|primera|segunda|tercera)\b", re.I
)


_CAMBIO_DE_CANTIDAD = re.compile(
    r"\b(solo|sola|solamente|unicamente|mejor|ya no|cambi\w*|al final|en vez|"
    r"nada mas|que sean|agreg\w*|a[nñ]ad\w*|otra huellita|una mas|sumale|quita\w*)\b"
    r"|\b(2|3|dos|tres)\s+huellitas\b|\bde\s+(1|2|3|una|dos|tres)\b",
    re.I,
)


_LA_HUELLITA = re.compile(r"\b(toda\s+)?la\s+huellita\b(?!s)", re.I)
_OTRA_CANTIDAD = re.compile(
    r"\b(2|3|dos|tres|otra|otras|segunda|tercera|cada|ambas|las huellitas)\b", re.I
)


def habla_de_una_sola_huellita(texto: str | None) -> bool:
    """«Toda la huellita en el mismo tono» = un anillo de 1 (así lo lee Lía)."""
    limpio = _sin_tildes(texto or "")
    return bool(_LA_HUELLITA.search(limpio)) and not _OTRA_CANTIDAD.search(limpio)


def cambia_la_cantidad(texto: str | None) -> bool:
    """¿La clienta está CAMBIANDO una cantidad que ya había dicho?

    «Una huella negra» después de «son dos huellitas» describe una de las dos,
    no baja el anillo a 1 (pasó al repasar y se creó un pedido de 1 huellita).
    """
    return bool(_CAMBIO_DE_CANTIDAD.search(_sin_tildes(texto or "")))


#: «el de 3 huellitas», «quiero dos», «de una»: un número que de verdad habla
#: de CUÁNTAS huellitas. Más estrecho que `_CANTIDAD_ESCRITA`, que reconoce
#: «una» suelta y por eso valía para «una foto de un anillo».
_CUANTAS_HUELLITAS = re.compile(
    r"\b(?:de\s+|el\s+de\s+|quiero\s+|son\s+|ser[ií]an?\s+)?"
    r"(1|2|3|un|una|uno|dos|tres)\s+huellitas?\b"
    r"|\b(?:el\s+de|quiero\s+el\s+de|ser[ií]a\s+el\s+de)\s+(1|2|3|un|una|uno|dos|tres)\b",
    re.I,
)
_EN_NUMERO = {
    "1": 1,
    "un": 1,
    "una": 1,
    "uno": 1,
    "2": 2,
    "dos": 2,
    "3": 3,
    "tres": 3,
}


#: Contesta «¿de cuántas huellitas?» con un número a secas: «De una», «una»,
#: «dos», «de 3», «la de una».
_CANTIDAD_A_SECAS = re.compile(
    r"^\W*(?:de\s+|la\s+de\s+|el\s+de\s+|solo\s+|sola\s+)?(1|2|3|un|una|uno|dos|tres)"
    r"(?:\s+huellitas?)?\W*$",
    re.I,
)


def cantidad_contestada(texto: str | None, ultimo_de_lia: str | None) -> int | None:
    """«De una» justo después de «¿De cuántas huellitas lo quieres?» es 1.
    Real (Mónica, 07/10): «De una» -> «¿Lo quieres de 1, 2 o 3 huellitas?»."""
    pregunto = _sin_tildes(ultimo_de_lia or "").lower()
    if "huellita" not in pregunto or "?" not in pregunto:
        return None
    m = _CANTIDAD_A_SECAS.search(_sin_tildes(texto or "").strip())
    return _EN_NUMERO.get(m.group(1).lower()) if m else None


def cuantas_huellitas_escribio(texto: str | None) -> int | None:
    """El número de huellitas que ella escribió, si escribió alguno."""
    for m in _CUANTAS_HUELLITAS.finditer(_sin_tildes(texto or "")):
        crudo = m.group(1) or m.group(2)
        if crudo and (n := _EN_NUMERO.get(crudo.lower())):
            return n
    return None


#: Duda o compara entre cantidades: «3 o una», «¿cuál es la diferencia?»,
#: «no entendí lo de las huellitas», «¿qué significa lo de 2?».
_PREGUNTA_POR_LAS_CANTIDADES = re.compile(
    r"\bno\s+entend\w*|\bdiferencia\w*|\bque\s+significa\w*|\bque\s+es\s+lo\s+de\b"
    # «¿cuánto vale el de 1?» pregunta el precio, no lo escoge (17/10).
    r"|\bcuanto\s+(?:vale|valen|cuesta|cuestan|sale|salen|es)\b"
    r"|\bcomo\s+es\s+(?:lo|eso)\b"
    r"|\b(?:1|2|3|una|un|dos|tres)\b[^.?!]{0,30}?\bo\s+(?:de\s+|la\s+de\s+|el\s+de\s+)?"
    r"(?:1|2|3|una|un|dos|tres)\b",
    re.I,
)


def pregunta_por_las_cantidades(texto: str | None) -> bool:
    """¿Pregunta o compara cantidades en vez de escoger una? (17/10)"""
    return bool(_PREGUNTA_POR_LAS_CANTIDADES.search(_sin_tildes(texto or "")))


def escribe_una_cantidad(texto: str | None) -> bool:
    """«de 1», «dos huellitas», «solo una»… la clienta dijo un número."""
    return bool(_CANTIDAD_ESCRITA.search(_sin_tildes(texto or "")))


_HUELLITA_SINGULAR = re.compile(r"\bhuellita\b(?!s)", re.I)
_HABLA_DE_PAGO = re.compile(
    r"pagu[eé]|pago|pagad|transfer|consign|comprobante|soporte|abon[eé]|abono|"
    r"nequi|daviplata|bancolombia|llave"
    r"|los 60|mand[eé] (la plata|el dinero)|envi[eé] (la plata|el dinero)",
    re.I,
)


def cantidad_respaldada(
    cantidad: int,
    texto: str | None,
    ultimo_de_lia: str | None,
    antes: list[str] | None = None,
) -> bool:
    """¿Lo que escribió la clienta respalda esta cantidad? La cantidad cambia el precio.

    Vale si la escribe («dos», «solo una», «la primera»), si habla de «la huellita» en
    singular (y la cantidad es 1), o si afirma a una pregunta que ofrecía UNA sola
    cantidad («¿es de una huellita?» -> «sí»). Dos nombres NO son dos huellitas.

    `antes` son sus mensajes anteriores. Lo que escribió hace dos turnos también
    lo escribió ella: el 20/09 abrió con «quiero el de 3 huellitas» —que va a la
    apertura fija y no pasa por el modelo— y al turno siguiente el bot le
    preguntaba de cuántas lo quería. La guardia está para que un «sí» no elija
    por ella, no para hacerle repetir lo que ya dijo.
    """
    limpio = _sin_tildes(texto or "")
    # Preguntar por las cantidades no es escoger una (17/10: «como es lo de 3
    # huellitas o una no entendí» quedaba anotado como 3).
    if pregunta_por_las_cantidades(limpio):
        return False
    if escribe_una_cantidad(limpio):
        return True
    # Hacia atrás se mira con lupa: tiene que ser un número DE HUELLITAS y el
    # mismo que se está proponiendo. Con el detector suelto, la descripción de
    # una foto («una foto en la que dice…») validaba una cantidad que la
    # clienta nunca pidió (20/09).
    if any(cuantas_huellitas_escribio(m) == cantidad for m in antes or ()):
        return True
    if cantidad == 1 and _HUELLITA_SINGULAR.search(limpio):
        return True
    return (
        solo_afirma(texto)
        and escribe_una_cantidad(ultimo_de_lia)
        and not pregunto_cantidad_con_opciones(ultimo_de_lia)
    )


#: Lo que sí justifica llamar a Lía. Sin nada de esto, dar el nombre o la ciudad
#: no es motivo (pasó al repasar: «Valentina Pérez» -> PASAR_A_LIA).
_MOTIVO_PARA_LIA = re.compile(
    r"queja|reclam|devol|reembols|persona|humano|asesor|due[nñ]a|hablar con|"
    r"molest|estafa|robo|mal[oa]?\b|da[nñ]ad|rot[oa]\b|no me (lleg|sirv|qued)|"
    r"mayor|al por mayor|otro producto|collar|pulsera|arete|demand|denunc|"
    r"groser|idiota|hp\b|gonorrea|malpar|estupid",
    re.I,
)


def pasar_a_lia_sin_motivo(cambios: CambiosDelBorrador, texto: str | None) -> bool:
    """La jugada llama a Lía, pero la clienta solo dio su nombre o su ciudad."""
    solo_envio = (
        cambios.nombre_clienta
        or cambios.ciudad
        or cambios.direccion
        or cambios.cedula
        or cambios.celular
        or cambios.recoge_en_tienda is not None
    ) and not (
        cambios.cantidad_huellitas
        or cambios.huellitas
        or cambios.grabado
        or cambios.sin_grabado
        or cambios.talla
        or cambios.medida_cm
        or cambios.fecha_deseada
    )
    return bool(solo_envio) and not _MOTIVO_PARA_LIA.search(_sin_tildes(texto or ""))


#: Un pago se registra con un comprobante o con que ella diga, EXPLÍCITO y en
#: pasado, que ya pagó. Nombrar la plata no basta (Camilo, 21/09):
#:   · «Yo los pago cuando esté listo el anillo» → el modelo pidió
#:     RECIBIR_COMPROBANTE, «pago» bastaba, y el pedido quedó en revisión de
#:     pago sin que nadie hubiera pagado un peso;
#:   · «Cuenta» (pedía los datos) → «¡Recibido!», y ella: «Cuál recibido si no
#:     he hecho el pago».
_PAGO_HECHO = re.compile(
    r"\bya\s+(te\s+|le\s+)?(pague|transferi|consigne|abone|mande|envie|pase"
    r"|hice\s+(el\s+|la\s+)?(pago|transferencia|consignacion|abono))"
    r"|\b(pague|transferi|consigne|abone|pagamos|transferimos|consignamos)\b"
    r"|\b(hice|realice)\s+(el\s+|la\s+)?(pago|transferencia|consignacion|abono)"
    r"|\b(te\s+|le\s+)?(mande|envie|pase|adjunte)\s+(el\s+|la\s+)?"
    r"(comprobante|soporte|pantallazo|captura)"
    r"|\bah[ií]\s+(te\s+)?(va|esta)\s+(el\s+|la\s+)?(comprobante|soporte"
    r"|pantallazo|captura|pago|transferencia)"
    r"|\b(pago|abono|transferencia)\s+(ya\s+)?(hech[oa]|list[oa]|realizad[oa])\b",
    re.I,
)
#: «cuando pague», «apenas transfiera»: subjuntivo, todavía no pasó.
_SUBJUNTIVO_DE_PAGO = re.compile(
    r"\b(cuando|apenas|si|en\s+cuanto)\s+(le\s+|te\s+)?(pague|transfiera|consigne"
    r"|abone)\w*",
    re.I,
)
#: «no he hecho el pago», «todavía no transferí»: lo contrario de pagar.
_PAGO_NEGADO = re.compile(
    r"\b(no|todavia\s+no|aun\s+no|nunca)\s+(he\s+|e\s+|hemos\s+|te\s+|le\s+)?"
    r"(pagado|pague|transferido|transferi|consignado|consigne|abonado|abone"
    r"|hecho\s+(el|la)|mandado|enviado)",
    re.I,
)


def habla_de_pago(texto: str | None) -> bool:
    """¿Dice, explícito y en pasado, que YA pagó?

    «ya pagué», «ya transferí los 60», «te mandé el comprobante», «ahí va el
    pantallazo»: sí. «¿A qué cuenta?», «voy a transferir», «te pago más
    tarde», «los pago cuando esté listo», «no he hecho el pago»: no. No se
    interpreta un «de pronto ya pagó»: si no lo dice claro, no pagó.
    """
    t = _sin_tildes(texto or "")
    if not _HABLA_DE_PAGO.search(t) or _PAGO_NEGADO.search(t):
        return False
    return bool(_PAGO_HECHO.search(_SUBJUNTIVO_DE_PAGO.sub(" ", t)))


#: Pide las cuentas con todas las letras: «Cuenta», «¿a qué Nequi?», «me pasas
#: los datos». Entonces se le mandan aunque se hayan mandado hace un turno.
_PIDE_LAS_CUENTAS = re.compile(
    r"^\W*(la\s+|las\s+|el\s+|los\s+)?(cuentas?|numero(\s+de\s+cuenta)?|nequi"
    r"|daviplata|bancolombia|datos(\s+de\s+pago)?|medios\s+de\s+pago)\W*$"
    r"|\b(a\s+(que|cual)\s+|cual(es)?\s+(es\s+|son\s+)?(la\s+|las\s+|el\s+)?"
    # Con hasta tres palabras en medio (05/10, Yesi: «Regálame por fis la
    # cuenta para realizar el abono» no se reconocía y la cuenta no salió).
    r"|(me|nos)\s+(pasas|das|mandas|repites|regalas|envias|compartes|pasa|regala"
    r"|manda|envia|comparte)\s+(?:\w+\s+){0,3}?"
    r"|(pasame|dame|mandame|regalame|compartime|comparteme|enviame|regalanos)\s+"
    r"(?:\w+\s+){0,3}?)(cuentas?|numero|nequi|daviplata|bancolombia"
    r"|datos|medios\s+de\s+pago)\b"
    r"|\b(a\s+)?donde\s+(te\s+|le\s+)?(transfiero|consigno|pago|deposito|abono)\b",
    re.I,
)
#: Da a entender que quiere pagar, sin pedir «la cuenta» con esas palabras
#: (Camilo, 05/10: «con que diga sí lo quiero, ¿cómo te pago?, que la mande»).
_QUIERE_PAGAR = re.compile(
    r"\bcomo\s+(te\s+|le\s+|les\s+)?(pago|abono|transfiero|consigno|cancelo)\b"
    r"|\bcomo\s+(es|seria|hago|hacemos|realizo|te\s+hago)\s+(el|para\s+el|para)\s+"
    r"(pago|pagar|abono|abonar)\b"
    r"|\bpara\s+(hacer|realizar|enviar|mandar)(te)?\s+el\s+(pago|abono)\b"
    r"|\b(quiero|quisiera|voy\s+a|vamos\s+a|puedo|podria|me\s+gustaria|ya\s+quiero)"
    r"\s+(ir\s+)?(pagar|pagarlo|pagarla|pagando|abonar|abonando|transferir"
    r"|consignar|adelantar|adelantando|separar(lo|la)?|hacer\s+el\s+(pago|abono))\b"
    r"|\b(listo|lista|listos|listas)\s+para\s+(pagar|abonar|transferir)\b"
    r"|\bya\s+te\s+(pago|abono|transfiero|consigno)\b"
    r"|\b(datos|cuentas?|numero)\s+(para|de)\s+(pagar|pago|abonar|abono|transferir"
    r"|consignar)\b",
    re.I,
)
#: …pero no si es para después: «después te pago», «todavía no», «la quincena».
_PAGA_DESPUES = re.compile(
    r"\b(no\s+(tengo|puedo|voy|quiero)|todavia\s+no|aun\s+no|despues|luego"
    r"|mas\s+(tarde|adelante)|manana|otra\s+semana|otro\s+mes|cuando\s+me\s+paguen"
    r"|quincena)\b",
    re.I,
)


_ES_COMPROBANTE = re.compile(
    r"comprobante|transferencia|consignacion|soporte\s+de(l)?\s+pago"
    r"|captura\s+de(l)?\s+(pago|abono|saldo)|pantallazo\s+de(l)?\s+(pago|abono)"
    # 04/10: «Envió una captura de un movimiento realizado por $59.700…» no se
    # reconocía y el bot le preguntó si quería mandar «otro comprobante».
    r"|movimiento|transaccion|envio\s+(de\s+)?(dinero|plata)|recibo\s+de\s+pago"
    r"|pago\s+(realizado|exitoso|enviado|hecho)|envio\s+exitoso|pagaste|enviaste",
    re.I,
)
#: Plata en lo que se leyó: «$59.700», «60.000 pesos», «Nequi», «Bancolombia».
#: Con el pago pendiente, una foto con plata ES un comprobante (`parece_un_pago`).
_PLATA_EN_LA_FOTO = re.compile(
    r"\$\s?\d|\d[\d.]*\s*(pesos|cop)\b|nequi|daviplata|bancolombia|davivienda"
    r"|bre-?b|llave",
    re.I,
)
#: El mensaje DUDA del comprobante. El bot no lo juzga nunca: lo verifica Lía.
_DUDA_DEL_COMPROBANTE = re.compile(
    r"otro\s+comprobante|no\s+coincide|no\s+cuadra|no\s+corresponde|otra\s+persona"
    r"|otra\s+cuenta|no\s+es\s+(el|la|un|una)\s+(comprobante|valor|monto|cuenta)"
    r"|monto\s+(distinto|diferente)|valor\s+(distinto|diferente)|seguro\s+que"
    r"|no\s+(veo|aparece)\s+(el|la|un|una)?\s*(pago|nombre|valor|monto)"
    r"|incomplet|falta(n)?\s+\$|\$\s?59",
    re.I,
)
_NO_ES_COMPROBANTE = re.compile(
    r"\bno\s+(es|parece|se\s+ve\s+como)\s+(un\s+|el\s+|una\s+)?"
    r"(comprobante|transferencia)",
    re.I,
)


def llego_un_comprobante(lectura: str, descripciones: list[str]) -> bool:
    """¿Lo que se vio del adjunto dice que es un comprobante?

    Pasó al repasar (21/09): llegó la foto del comprobante, el modelo escribió
    «Envió el comprobante de pago del abono»… y no pidió RECIBIR_COMPROBANTE.
    El pago no quedaba en ninguna parte. Un comprobante que llegó no se puede
    perder: si lo que el modelo mismo leyó lo llama comprobante, se registra.
    """
    for texto in (lectura, *descripciones):
        t = _sin_tildes(texto or "")
        if _ES_COMPROBANTE.search(t) and not _NO_ES_COMPROBANTE.search(t):
            return True
    return False


def parece_un_pago(lectura: str, descripciones: list[str]) -> bool:
    """¿Lo que se vio de la foto tiene plata (un valor, un banco)?

    Solo se usa cuando se está esperando un pago (las cuentas ya salieron): ahí
    una foto con plata es el comprobante, la describa el modelo como la
    describa. 04/10: «captura de un movimiento realizado por $59.700».
    """
    return any(
        _PLATA_EN_LA_FOTO.search(_sin_tildes(t or "")) for t in (lectura, *descripciones)
    )


def duda_del_comprobante(texto: str | None) -> bool:
    """¿El mensaje cuestiona el comprobante (valor, destinatario, «otro»)?

    Camilo (04/10): el bot no juzga un comprobante. Si el valor no es exacto
    (el costo de la transferencia), el nombre sale enmascarado o es otra cuenta
    suya, lo revisa Lía: a la clienta se le dice que lo recibimos y que Lía lo
    verifica, y a Lía se le deja lo que se vio."""
    return bool(_DUDA_DEL_COMPROBANTE.search(_sin_tildes(texto or "")))


def pide_las_cuentas(texto: str | None) -> bool:
    """¿Está pidiendo, explícito, a dónde pagar?"""
    return bool(_PIDE_LAS_CUENTAS.search(_sin_tildes(texto or "").strip()))


def quiere_la_cuenta(texto: str | None) -> bool:
    """¿Pide la cuenta o da a entender que quiere pagar YA? (05/10)

    «Regálame por fis la cuenta», «sí lo quiero, ¿cómo te pago?», «quiero ir
    abonando»: sí, aunque falten datos del pedido (se le mandan y se le pide
    con cariño lo que falta). «Después te pago», «todavía no», «ya pagué»
    (eso es el comprobante): no.
    """
    t = _sin_tildes(texto or "").strip()
    if not t or paga_despues(texto):
        return False
    return bool(_PIDE_LAS_CUENTAS.search(t) or _QUIERE_PAGAR.search(t))


def paga_despues(texto: str | None) -> bool:
    """«Después te pago», «todavía no», «ya pagué»: no es para mandarle la cuenta."""
    return habla_de_pago(texto) or bool(_PAGA_DESPUES.search(_sin_tildes(texto or "")))


_VALOR_DE_CANTIDAD = {
    "1": 1,
    "una": 1,
    "uno": 1,
    "sola": 1,
    "solo": 1,
    "2": 2,
    "dos": 2,
    "3": 3,
    "tres": 3,
}


def pregunto_cantidad_con_opciones(mensaje: str | None) -> bool:
    """La pregunta ofrece MÁS DE UNA cantidad: «¿de 1 o de 2?», «¿1, 2 o 3?».

    Se cuentan cantidades distintas y no un patrón fijo: la pregunta que el propio
    sistema hace («¿De 1 huellita con los nombres, o de 2 (una por cada uno)?») no
    decía «2 huellitas», y un «listo» a esa pregunta llegó a fijar 2 huellitas.
    """
    if _OPCIONES_DE_CANTIDAD.search(mensaje or ""):
        return True
    palabras = re.findall(r"[a-z0-9]+", _sin_tildes(mensaje or "").lower())

    def es_cantidad(i: int) -> bool:
        return 0 <= i < len(palabras) and palabras[i] in _VALOR_DE_CANTIDAD

    def ofrecida(i: int) -> bool:
        # Una cantidad OFRECIDA va pegada a «huellita» o en una lista con otra
        # («1, 2 o 3», «de una o de dos»). «Serían 2 huellitas: UNA para Sakura y
        # otra para Muñeco» ofrece una sola: la «una» de ahí no es opción.
        if any(p.startswith("huellit") for p in palabras[i + 1 : i + 3]):
            return True
        for paso in (1, -1):
            j, con_o = i + paso, False
            while 0 <= j < len(palabras) and (
                palabras[j] in ("o", "u", "de") or palabras[j].startswith("huellit")
            ):
                con_o = con_o or palabras[j] in ("o", "u")
                j += paso
            # Pegadas («1, 2 o 3») o separadas por una «o» («1 huellita o de 2»).
            if es_cantidad(j) and (abs(j - i) == 1 or con_o):
                return True
        return False

    distintas = {
        _VALOR_DE_CANTIDAD[p]
        for i, p in enumerate(palabras)
        if es_cantidad(i) and ofrecida(i)
    }
    return len(distintas) >= 2


#: Por debajo de esto una frase corta («¡Con gusto! 💓») se puede repetir sin
#: sonar a máquina: una persona también lo hace.
LARGO_MINIMO_REPETIDA = 20


def _comparable(texto: str) -> str:
    t = re.sub(r"[^a-z0-9 ]", " ", _sin_tildes(texto or "").lower())
    return " ".join(t.split())


def sin_colores(b: Borrador) -> None:
    """Los deja SIN escoger, para volver a preguntárselos.

    El 20/09 una clienta dijo «No ya no me gusto» del fucsia, nunca escogió
    otro, y el borrador siguió en fucsia mientras la conversación avanzaba al
    grabado: ese anillo se habría fabricado del color que ella rechazó.

    No había forma de DESESCOGER —un `None` en los cambios significa «esto no
    cambia», nunca «quítalo»—, así que el modelo entendía lo que ella quería
    decir y no tenía con qué decirlo.
    """
    for h in b.huellitas:
        h.corazon = None
        h.dedos = None
        h.dedos_alternos = []
    b.ultimas_vistas = []


def repite_lo_dicho(mensaje: str, anteriores: list[str]) -> str | None:
    """El renglón de un mensaje anterior que este mensaje casi repite.

    Pasó al repasar: «¡Dale! Quedo atenta al comprobante 🙌» cuatro turnos
    seguidos mientras la clienta preguntaba otras cosas, y «¿En cuál ciudad te lo
    enviamos?» otras cuatro. Nadie que atiende de verdad escribe así.
    """
    nuevo = _comparable(mensaje)
    if len(nuevo) < LARGO_MINIMO_REPETIDA:
        return None
    for anterior in anteriores:
        for renglon in (anterior or "").split("\n"):
            viejo = _comparable(renglon)
            if len(viejo) < LARGO_MINIMO_REPETIDA:
                continue
            corto, largo = sorted((nuevo, viejo), key=len)
            if corto in largo or SequenceMatcher(None, nuevo, viejo).ratio() >= 0.75:
                return renglon.strip()
    return None


def _sin_tildes(texto: str) -> str:
    normal = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in normal if not unicodedata.combining(c))


def _nota(b: Borrador, nota: str) -> None:
    if nota not in b.notas:
        b.notas.append(nota)


# ══════════════════════════════════════════════════════════════════════════
#  EL VIGILANTE: lo que el modelo no puede decir aunque quiera
# ══════════════════════════════════════════════════════════════════════════

_MONTO = re.compile(
    r"\$\s?\d{1,3}(?:[.,]\d{3})+|\b\d{1,3}(?:\.\d{3})+\b|\b\d{2,3}\s?mil\b", re.I
)
_CUENTA = re.compile(r"\d[\d\s-]{6,}\d")
#: Una fecha (12/03/2015, 5-8-24, 12.03.2015): no es un número de cuenta.
_FECHA = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")
#: Lo que el modelo tiende a inventar para dar confianza y NO sabe: cuentas de
#: redes, enlaces, años en el mercado, cantidad de clientas. Pasó al repasar
#: una clienta desconfiada: «tenemos Instagram @lia_accesorios con cientos de
#: clientes». Ni el usuario ni el número eran verdad conocida.
_INVENTOS = re.compile(
    r"@[A-Za-z0-9_.]{3,}|https?://|www\.|\.com\b"
    r"|\b(cientos|miles|much[ií]simas?|m[aá]s\s+de\s+\d+)\s+de\s+"
    r"(clientes|clientas|anillos|pedidos|ventas)\b"
    r"|\bllevamos\s+(m[aá]s\s+de\s+)?(\d+|un|dos|tres|varios|muchos)\s+a[nñ]os",
    re.I,
)
#: Lo que SÍ es verdad y da confianza (Camilo, 13/10): la página y el Instagram
#: de Lía. La página dice «Creando piezas especiales desde 2019» (no «más de 8
#: años»: eso no se dice). Se quitan antes de buscar inventos.
REDES_DE_VERDAD = (
    "https://www.lunajoyas.example/",
    "https://lunajoyas.example/",
    "https://www.lunajoyas.example",
    "https://lunajoyas.example",
    "www.lunajoyas.example",
    "lunajoyas.example",
    "https://www.instagram.com/lunajoyas/",
    "https://instagram.com/lunajoyas",
    "https://www.instagram.com/lunajoyas",
    "instagram.com/lunajoyas",
    "@lunajoyas",
)
_LO_VERDADERO = re.compile(
    "|".join(re.escape(r) for r in sorted(REDES_DE_VERDAD, key=len, reverse=True)),
    re.I,
)


def inventa_datos_del_negocio(frase: str) -> bool:
    """¿Inventa redes, enlaces, trayectoria o clientas? Las de verdad no cuentan."""
    return bool(_INVENTOS.search(_LO_VERDADERO.sub("", frase)))


#: Saludar con un nombre que no es el del negocio. El 20/09 el bot dijo
#: «Bienvenida a Anillo Vial»: leyó la calle del punto de recogida y la tomó
#: por el nombre de la marca. Es de las cosas que más rápido delatan que del
#: otro lado hay una máquina, y encima en el primer mensaje.
#: Nombres de color que NO son de ninguna bolsita del muestrario (30/09). Si la
#: clienta dice «verde menta», el bot no puede contestarle «¡el verde menta te
#: queda divino!»: le confirma una piedra que no existe y ella nunca sabe cuál
#: le van a poner. Tiene que nombrarla como el muestrario («verde oliva»).
_COLOR_FUERA_DEL_MUESTRARIO = re.compile(
    r"(?i)\b("
    r"menta|turquesa|lavanda|violeta|salm[oó]n|coral|champa[ñn]a|champagne|"
    r"melocot[oó]n|vinotinto|magenta|aguamarina|palo de rosa|rosa palo|"
    r"azul (?:claro|clarito|oscuro|marino|cielo|london)|"
    r"verde (?:claro|clarito|oscuro|lim[oó]n|menta|agua)|"
    # Un apellido que no es de ninguna bolsita: «naranja claro», «rojo
    # fuerte» (29/09: «Perfecto, naranja claro 🧡»; solo hay UN naranja).
    r"(?:naranja|roj[oa]|rosad[oa]|rosa|morad[oa]|amarill[oa]|lila|fucsia|"
    r"durazno|celeste|negr[oa]|blanc[oa])s?\s+(?:claro|clarito|fuerte|oscuro|"
    r"oscurito|pastel|bajito|encendido|intenso|ne[oó]n|p[aá]lido)|"
    r"dorad[oa]s?|platead[oa]s?|gris|caf[eé]|marr[oó]n|beige|nude|"
    r"rub[ií]|zafiro|amatista"
    r")\b"
)
#: …salvo que la frase sea justo la guía: «no tenemos gris», «el más parecido
#: es el negro», «ese en el muestrario se llama verde oliva».
_GUIA_DE_COLOR = re.compile(
    r"(?i)\bno\s+(?:tenemos|manejamos|hay|trabajamos|contamos|existe)|"
    r"\bno\s+est[aá]\b|parecid|similar|en\s+(?:vez|lugar)\s+de|"
    r"equivale|corresponde|se\s+llama|llamamos|muestrario"
)


def _color_que_no_existe(frase: str) -> str | None:
    """El problema si la frase nombra como piedra un color que no existe.

    Lo que sea parte de un nombre VIGENTE del muestrario pasa: si Lía llamó a
    una bolsita «celeste turquesa» o «champagne» (panel → Colores), el bot
    tiene que poder decirlo.
    """
    from app.domain.personalizacion import nombres_del_muestrario

    oficiales = [_sin_tildes(n).lower() for n in nombres_del_muestrario()]
    for m in _COLOR_FUERA_DEL_MUESTRARIO.finditer(frase):
        palabra = _sin_tildes(m.group(0)).lower()
        if any(palabra in nombre for nombre in oficiales):
            continue
        if _GUIA_DE_COLOR.search(frase):
            return None
        return (
            f"nombra un color que no está en el muestrario ({m.group(0)!r}): "
            "di el nombre de la bolsita (" + ", ".join(nombres_del_muestrario()) + ")"
        )
    return None


#: Una pregunta por los datos de la guía (ciudad, dirección, cédula…).
_PIDE_DATOS_DE_LA_GUIA = re.compile(
    r"\b(ciudad|direcci[oó]n|c[eé]dula|barrio|celular|datos\s+(?:de|para)\s+(?:el\s+)?"
    r"env[ií]o|datos\s+para\s+la\s+gu[ií]a)\b",
    re.I,
)


def quitar_pedida_de_envio(texto: str) -> tuple[str, bool]:
    """Quita las PREGUNTAS por los datos de envío (regla de Camilo, 20/09: se
    piden al final, con las fotos del anillo listo). El prompt lo dice, pero el
    modelo a veces no: prueba de verdad, 04/10, «¡Recibido! 🙌 Ya tomé tu
    pedido 🫶 ¿A qué ciudad te lo enviamos cuando esté listo?». Las frases que
    no preguntan se quedan. Devuelve (texto, si quitó algo)."""
    quito = False
    lineas = []
    for linea in (texto or "").split("\n"):
        quedan = []
        for f in re.split(r"(?<=[.!?])\s+", linea):
            if "?" in f and _PIDE_DATOS_DE_LA_GUIA.search(f):
                quito = True
                continue
            quedan.append(f)
        if quedan or not linea.strip():
            lineas.append(" ".join(quedan))
    return "\n".join(lineas).strip(), quito


def una_sola_pregunta(mensaje: str, final: str) -> tuple[str, str, int]:
    """Deja la PRIMERA pregunta del turno y quita las demás (ADR 0024).

    El prompt lo pide, pero el modelo no siempre lo cumple: el 30/09, a «una
    roja y la otra verde oliva» le llegó «¿Quieres cada huellita toda de ese
    color, o combinar? Y, ¿qué nombres te gustaría grabar?». Dos preguntas
    sobre cosas distintas: contesta una y la otra se pierde. Las frases que no
    preguntan se quedan. Devuelve (mensaje, final, cuántas se quitaron).
    """
    vista = False
    quitadas = 0

    def podar(texto: str) -> str:
        nonlocal vista, quitadas
        lineas = []
        for linea in (texto or "").split("\n"):
            quedan = []
            # El emoji que venía pegado a la pregunta quitada («… grabar? 🐾»)
            # se va con ella: suelto no dice nada.
            saltando = False
            for f in re.split(r"(?<=[.!?])\s+", linea):
                if "?" in f:
                    if vista:
                        quitadas += 1
                        saltando = True
                        continue
                    vista = True
                elif saltando and not any(c.isalnum() for c in f):
                    continue
                saltando = False
                quedan.append(f)
            if quedan or not linea.strip():
                lineas.append(" ".join(quedan))
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()

    mensaje = podar(mensaje)
    final = podar(final)
    return mensaje, final, quitadas


#: Frases que le CONFIRMAN el pedido («déjame confirmarte: …», «así queda»).
_CONFIRMA_EL_PEDIDO = re.compile(
    r"(?i)confirm|as[ií]\s+(?:queda|va|est[aá])|tu\s+anillo\s+(?:es|ser[aá]|queda)"
)


def _cantidad_que_no_es(frase: str, b: Borrador) -> str | None:
    """Al confirmar, la cantidad tiene que ser la del pedido: cambia el precio.

    29/09: el resumen decía 2 huellitas y el mensaje de debajo, «déjame
    confirmar: 1 huellita, corazón rosado…». Solo se mira en las frases que
    confirman: ofrecer «¿de 1, 2 o 3?» o cotizar «con 3 serían…» es legítimo.
    """
    if not b.cantidad or not _CONFIRMA_EL_PEDIDO.search(frase):
        return None
    dice = cuantas_huellitas_escribio(frase)
    if dice is None or dice == b.cantidad:
        return None
    return f"confirma {dice} huellita(s) y el pedido es de {b.cantidad}"


_OTRO_NOMBRE = re.compile(
    # El disparador da igual en mayúsculas o minúsculas; el NOMBRE no:
    # tiene que empezar en mayúscula para que «bienvenida a nuestra
    # tienda» no cuente. Y si «Lía» viene cerca, es el nombre bueno.
    r"(?i:bienvenid[oa]s?\s+a|somos)\s+"
    r"(?![^\n]{0,14}Luna\b)"
    r"[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]*(\s+[A-ZÁÉÍÓÚÑ0-9#][\w…]*){0,3}"
)

_PROMESAS_PROHIBIDAS = re.compile(
    r"(pago|abono|transferencia)\s+(confirmad|verificad|aprobad)"
    r"|confirm[eé]\s+(tu|el)\s+(pago|abono)"
    r"|ya\s+(verifiqu[eé]|confirm[eé])"
    # «Ya recibí tu transferencia» es lo mismo que «ya recibí tu pago», y
    # se colaba entero (20/09, probando de punta a punta).
    r"|(recib[ií]|recibimos)\s+(tu|el|la)\s+(pago|abono|dinero|transferencia|consignaci[oó]n|giro)"
    # 19/09, con una clienta: «Perfecto, ya lo vimos 🙌». Suena a confirmado
    # y no lo estaba: el comprobante lo mira Lía en el banco, no el bot.
    r"|ya\s+(lo\s+)?(vimos|vi|veo|lo\s+tengo|nos\s+lleg[oó]|me\s+lleg[oó])"
    r"|(qued[oó]|entr[oó])\s+(el\s+)?(pago|abono|saldo)",
    re.I,
)


#: «talla 7», «talla 7.5», «talla 7,25», «talla 7¾».
_TALLA_DICHA = re.compile(
    r"\btalla\s+(?:es\s+(?:la\s+)?|la\s+|de\s+)?"
    r"(\d{1,2}(?:[.,]\d{1,2}|\s?[¼½¾])?)(?![\d¼½¾])",
    re.I,
)
#: «te confirmo la talla», «Lía te confirma tu talla», «revisamos tu medida».
_PROMETE_CONFIRMAR_TALLA = re.compile(
    r"confirm\w*\s+(?:tu\s+|la\s+)?talla|revis\w*\s+(?:tu\s+|la\s+)(?:talla|medida)"
    r"|talla\s+(?:te\s+)?la\s+confirm",
    re.I,
)
#: «¿la talla 6 es la definitiva?», «¿estás segura de tu talla?».
_DUDA_DE_LA_TALLA = re.compile(
    r"talla\b.{0,25}\b(definitiva|segura|correcta|exacta)\b"
    r"|\bsegura\b.{0,25}\btalla\b",
    re.I,
)
_PEDIDO_TOMADO = re.compile(
    r"ya\s+tom[eé]\s+tu\s+pedido|(queda|qued[oó]|est[aá]|va)\s+(ya\s+)?en\s+producci[oó]n"
    r"|list[oa]\s+para\s+(pasar\s+)?(a|al|el|en\s+el)?\s*taller"
    r"|ya\s+(queda|qued[oó])\s+(todo\s+)?(listo|registrado)"
    # «Perfecto, ya queda lista tu orden» (repaso 17/09, sin abono todavía).
    r"|(queda|qued[oó]|est[aá])\s+(ya\s+)?list[oa]\s+tu\s+(orden|pedido)"
    r"|tu\s+(orden|pedido)\s+(ya\s+)?(queda|qued[oó]|est[aá])\s+(list[oa]|registrad[oa])",
    re.I,
)
#: «Quedo atenta al comprobante», «me mandas el soporte», «transfiere»: hablar de
#: pagar sin haberle dado a dónde es dejarla sin poder hacerlo (pasó 19/09).
_ESPERA_PAGO = re.compile(
    r"comprobante|soporte\s+de\s+pago|pantallazo|transfer\w*|consign\w*"
    r"|(me\s+)?(env[ií]as|mandas)\s+(el\s+|los\s+)?(pago|abono|60)",
    re.I,
)
#: Lo que el anillo ya dejó atrás: si está listo o despachado, decir «está en el
#: taller» o «te aviso cuando esté listo» es contarle otra historia (pasó 19/09).
_EN_TALLER = re.compile(
    r"en\s+(el\s+)?taller|en\s+producci[oó]n|fabric[aá]ndo|"
    r"te\s+(aviso|escribo|cuento|mando\s+las\s+fotos)\s+(apenas|cuando|tan\s+pronto)",
    re.I,
)
#: EXPLICAR para qué es el abono no es decir que ya está en el taller (13/10, a
#: quien le da miedo abonar: «el abono es lo que nos permite empezarlo en el
#: taller» se borraba). Decir que YA está allí sigue prohibido.
_EXPLICA_EL_ABONO = re.compile(
    r"\babon\w*[^.!?]{0,80}\b(?:permit\w*|para|empez\w*|pas\w*|entr\w*|llev\w*)\b"
    r"[^.!?]{0,40}\btaller\b"
    r"|\btaller\b[^.!?]{0,40}\b(?:cuando|apenas|despu[eé]s\s+de|con\s+(?:el|tu))\b"
    r"[^.!?]{0,30}\babon",
    re.I,
)
_YA_ESTA_EN_EL_TALLER = re.compile(
    r"\bya\s+(?:est[aá]|entr[oó]|pas[oó]|se\s+est[aá])\b|\best[aá]\s+en\s+(?:el\s+)?taller",
    re.I,
)


def explica_el_abono(frase: str) -> bool:
    """«El abono es lo que nos permite empezarlo en el taller»: explica, no miente."""
    return bool(_EXPLICA_EL_ABONO.search(frase)) and not _YA_ESTA_EN_EL_TALLER.search(
        frase
    )


#: Solo en PASADO: «te lo despachamos apenas pagues» es una promesa válida.
_DESPACHADO = re.compile(
    r"despachad[oa]|ya\s+(se\s+)?(te\s+)?(lo\s+)?despach\w*|"
    r"(va|est[aá])\s+en\s+camino|ya\s+(te\s+)?(lo\s+)?(envi|mand)[eé]\b",
    re.I,
)
#: Estados del pedido en los que el anillo ya salió del taller.
YA_TERMINADO = {
    "PRODUCCION_LISTA",
    "ESPERANDO_SALDO",
    "SALDO_PAGADO",
    "DESPACHADO",
    "ENTREGADO",
}
YA_DESPACHADO = {"DESPACHADO", "ENTREGADO"}
#: Antes de que el anillo se fabrique. Aquí «te lo despachamos» es mentira.
ANTES_DEL_TALLER = {"ESPERANDO_ANTICIPO", "EN_REVISION_PAGO", "ANTICIPO_PAGADO"}
#: Antes de que el anillo exista: el taller empieza cuando Lía verifica el
#: abono en el banco, no cuando la clienta dice que transfirió.
ANTES_DE_FABRICAR = {"ESPERANDO_ANTICIPO", "EN_REVISION_PAGO"}
#: «te lo despachamos», «sale para tu casa»: en futuro y por eso no lo coge
#: `_DESPACHADO`, que solo mira el pasado.
_PROMETE_DESPACHO = re.compile(
    r"(te\s+lo\s+)?despach\w*|sale\s+(para|hacia)\s+(tu|su)\s+"
    r"(casa|ciudad|direcci[oó]n)|lo\s+(envi|mand)\w*\s+(ya|hoy|enseguida)",
    re.I,
)

#: «Tu pedido entra al taller ahora mismo», «empezamos a fabricarlo», «en 10 a
#: 15 días te comparto las fotos»: dar por arrancada la fabricación. Pasó el
#: 21/09 con una clienta que todavía NO había pagado el abono: el vigilante no
#: lo vio porque solo buscaba «EN el taller», y ella entendió que el pedido ya
#: estaba tomado. El anillo entra al taller con el abono, no antes.
_ARRANCA_EL_TALLER = re.compile(
    r"\b(entra|entr[oó]|pasa|pas[oó]|ingresa|ingres[oó]|va|se\s+va|sale|queda"
    r"|qued[oó])\s+(ya\s+|de\s+una\s+|directo\s+|directamente\s+|hoy\s+)?"
    r"(al|para\s+el|a\s+el)\s+taller"
    r"|\b(empez|comenz|arranc|inici)\w*\s+(ya\s+|hoy\s+)?(a\s+)?"
    r"(fabric|hac|elabor|trabaj)\w*"
    r"|\ben\s+\d{1,2}\s*(a|-|y)\s*\d{1,2}\s+d[ií]as\s+(te\s+)?"
    r"(comparto|mando|env[ií]o|paso|tengo|entrego|muestro)",
    re.I,
)
#: «¡Recibido!» cuando no ha llegado nada. 21/09: pidió «Cuenta», le llegaron
#: los datos y debajo «¡Recibido!»; ella: «Cuál recibido si no he hecho el
#: pago». Solo se dice cuando llegó un comprobante o dijo que ya pagó.
_ACUSA_RECIBO = re.compile(
    r"\brecibid[oa]s?\b|\b(lo|la|los)\s+recib[ií]\b"
    r"|\brecib[ií]\s+(tu|el|la)\s+(comprobante|soporte|pantallazo|captura)"
    r"|\bya\s+(me\s+)?lleg[oó]\s+(tu|el)\s+(comprobante|pago|soporte)",
    re.I,
)
#: «ese recibido era porque leí mal»: habla DE la palabra, no acusa recibo.
_CITA_EL_RECIBIDO = re.compile(r"\b(ese|el|un|del|mi)\s+[«\"']?recibid", re.I)
#: Lo mismo dicho como CONDICIÓN sí es verdad y es justo lo que hay que
#: decir: «apenas hagas el abono, tu pedido entra al taller».
_CON_CONDICION = re.compile(
    r"\b(apenas|cuando|en\s+cuanto|tan\s+pronto|una\s+vez|si|despu[eé]s\s+del?"
    r"|luego\s+del?|para\s+(que|pasar|poder|iniciar|empezar|entrar)"
    r"|con\s+(el|tu)\s+abono|al\s+(hacer|recibir|verificar))\b",
    re.I,
)
#: Pedir el envío JUNTO CON EL ABONO. Nunca: el envío se paga al recibir, o
#: —si ella quiere pagarlo antes— con el SALDO, cuando el anillo está listo.
#: 21/09: «¿Transfieres los $60.000 del abono + los $18.000 del envío en una
#: sola transferencia?», a una clienta que solo quería que se lo dejaran en
#: portería.
#: Lo que puede haber entre «abono» y «envío». Una cifra no corta la frase:
#: «$18.000» lleva punto, y por ese punto se escapaba la frase del 21/09.
_HUECO = r"(?:[^.!?\n]|\.(?=\d))"
_ENVIO_CON_EL_ABONO = re.compile(
    rf"abono\b{_HUECO}{{0,40}}?(\+|\bm[aá]s\b|\by\s+(el|los)\b|\bjunto\s+con\b"
    rf"|\bcon\s+el\b|\bsumad\w*){_HUECO}{{0,30}}?env[ií]o"
    rf"|env[ií]o\b{_HUECO}{{0,40}}?(\+|\bm[aá]s\b|\by\s+(el|los)\b|\bjunto\s+con\b"
    rf"|\bcon\s+el\b){_HUECO}{{0,30}}?abono"
    r"|pag\w*\s+(el\s+)?env[ií]o\s+(de\s+una\s+vez\s+)?(ahora|ya\b|hoy|de\s+una)",
    re.I,
)
#: Si la frase dice CUÁNDO se paga el envío de verdad, no lo está juntando con
#: el abono: «el abono ahora y el envío con el saldo», «...lo pagas al recibir».
_ENVIO_EN_SU_MOMENTO = re.compile(
    r"al\s+recibir|contra\s*entrega|con\s+el\s+saldo|junto\s+con\s+el\s+saldo"
    r"|cuando\s+(el\s+anillo\s+)?est[eé]\s+list[oa]|cuando\s+te\s+llegue",
    re.I,
)

_CUENTAS_YA_DADAS = re.compile(
    r"(te\s+)?(pas[eé]|envi[eé]|mand[eé]|compart[ií])\s+(los\s+datos|las\s+cuentas|la\s+cuenta)"
    r"|(datos|cuentas)\s+(de\s+arriba|m[aá]s\s+arriba|que\s+te\s+(pas[eé]|envi[eé]))",
    re.I,
)


def _falso_segun_el_estado(
    frase: str, b: Borrador, estado_pedido: str = ""
) -> str | None:
    """Lo que el mensaje afirma y el estado real desmiente."""
    if (
        not b.talla_por_confirmar
        and _PROMETE_CONFIRMAR_TALLA.search(frase)
        # «Cuando me mandes la foto, te confirmo tu talla» sí es verdad.
        and not re.search(r"\b(cuando|apenas|en\s+cuanto|si\s+me)\b", frase, re.I)
    ):
        # No hay ninguna talla (ni foto de la regla) esperando a Lía: o ya
        # quedó, o ella todavía no la ha mandado. Prueba de verdad: con la talla
        # 6 lista, «en unos minutos te confirmo la talla» (05/10); y a quien se
        # fue a la joyería y no la había dado, lo mismo (07/10).
        return (
            "dice que va a confirmar la talla y no hay ninguna por confirmar (o ya "
            "quedó, o ella todavía no la ha dado)"
        )
    if (
        b.talla is not None
        and not b.talla_por_confirmar
        and b.talla_confirmada
        and _DUDA_DE_LA_TALLA.search(frase)
    ):
        # «¿la talla 6 es la definitiva?»: la talla ya quedó.
        return "duda de la talla que ella dijo (ya quedó: no se le pregunta más)"
    for m in _TALLA_DICHA.finditer(frase):
        dicha = leer_talla(m.group(1))
        if b.talla_por_confirmar and b.talla_revisar:
            return (
                f"dice talla {m.group(1)} y la talla todavía la tiene que confirmar Lía"
            )
        if b.talla is None or dicha != b.talla:
            return f"dice talla {m.group(1)} pero la guardada es {b.talla}"
    if _PEDIDO_TOMADO.search(frase) and not b.abono_reportado:
        return "da el pedido por tomado sin abono reportado"
    if (
        not b.abono_reportado
        and not b.saldo_reportado
        # Pagó con el pedido a medias: el comprobante SÍ llegó (queda anotado
        # para Lía aunque el pedido no haya nacido). «Recibido» es verdad.
        and not b.pagado_sin_pedido
        and _ACUSA_RECIBO.search(frase)
        and not _CITA_EL_RECIBIDO.search(frase)
    ):
        return (
            "dice «recibido» sin que haya llegado un comprobante ni diga que ya "
            "pagó (ella NO ha pagado: no lo des por recibido)"
        )
    if (
        not b.abono_reportado
        and estado_pedido in ("", "ESPERANDO_ANTICIPO")
        and _ARRANCA_EL_TALLER.search(frase)
        and not _CON_CONDICION.search(frase)
        and "?" not in frase
    ):
        return (
            "dice que el pedido entra al taller sin el abono (entra SOLO cuando "
            "pague el abono: díselo como condición, «apenas hagas el abono...»)"
        )
    if _ENVIO_CON_EL_ABONO.search(frase) and not _ENVIO_EN_SU_MOMENTO.search(frase):
        return (
            "junta el envío con el abono (el envío se paga al recibir o, si ella "
            "quiere pagarlo antes, JUNTO CON EL SALDO cuando el anillo esté listo)"
        )
    if _CUENTAS_YA_DADAS.search(frase) and not b.cuentas_enviadas:
        return "dice que ya mandó las cuentas y no se han mandado"
    if (
        _ESPERA_PAGO.search(frase)
        and not b.cuentas_enviadas
        and not b.abono_reportado
        and estado_pedido not in YA_TERMINADO
    ):
        return "habla de pagar o del comprobante sin haberle mandado las cuentas"
    if estado_pedido in YA_TERMINADO and _EN_TALLER.search(frase):
        return f"dice que el anillo sigue en el taller y ya está en {estado_pedido}"
    if (
        not estado_pedido
        and not b.abono_reportado
        and _EN_TALLER.search(frase)
        and not explica_el_abono(frase)
    ):
        return "dice que está en el taller y no hay pedido ni abono todavía"
    if (
        estado_pedido in ANTES_DE_FABRICAR
        and _EN_TALLER.search(frase)
        and not explica_el_abono(frase)
    ):
        # El anillo entra al taller cuando Lía verifica el abono en el banco,
        # no cuando la clienta dice que transfirió. Decirle que ya está allí
        # es prometerle una fecha que todavía no ha empezado a correr (20/09).
        return f"dice que está en el taller y el pedido está en {estado_pedido}"
    if estado_pedido not in YA_DESPACHADO and _DESPACHADO.search(frase):
        # SIN pedido también es mentira, y de la peor clase: se le está
        # diciendo «tu anillo va en camino» a alguien que todavía no ha
        # comprado nada. Antes esta guardia solo miraba cuando había pedido.
        donde = estado_pedido or "ni siquiera hay pedido todavía"
        return f"dice que ya se despachó y {donde}"
    # 19/09: tras el ABONO contestó «Apenas Lía lo verifique te lo despachamos».
    # Falso y además desmotiva: entre el abono y el despacho hay 10-15 días de
    # taller y un saldo por pagar. Prometer el despacho ahí es prometer mal.
    #
    # Con el SALDO en revisión la misma frase es verdad —lo siguiente ES el
    # despacho—, así que solo se prohíbe mientras lo que se espera es el abono.
    if (
        estado_pedido in ANTES_DEL_TALLER
        and not b.saldo_reportado
        and _PROMETE_DESPACHO.search(frase)
    ):
        return (
            "promete el despacho cuando lo que sigue es el taller "
            f"(el pedido está en {estado_pedido})"
        )
    return None


def _a_pesos(texto: str) -> int | None:
    t = texto.lower().replace("$", "").strip()
    m = re.match(r"(\d{1,3})\s?mil", t)
    if m:
        return int(m.group(1)) * 1000
    digitos = re.sub(r"\D", "", t)
    return int(digitos) if digitos else None


def vigilar(
    mensaje: str,
    montos_permitidos: set[int],
    borrador: Borrador | None = None,
    estado_pedido: str = "",
    promociones=(),
) -> tuple[str, list[str]]:
    """Quita del mensaje las frases que no puede decir. Nunca lo inventa.

    `promociones`: las vigentes hoy (17/10). Una frase que ofrece una que no
    está ahí («tenemos 2x1») se quita: el bot nunca inventa una promoción.

    Se quita la FRASE entera y no solo el número: «el envío te sale en $9.000»
    sin el número es peor que no decirlo.
    """
    problemas: list[str] = []
    lineas = []
    for linea in (mensaje or "").strip().split("\n"):
        buenas = []
        for f in re.split(r"(?<=[.!?])\s+", linea):
            mala = None
            for m in _MONTO.finditer(f):
                valor = _a_pesos(m.group(0))
                if valor is not None and valor not in montos_permitidos:
                    mala = f"monto no autorizado {m.group(0)!r}"
                    break
            # Las fechas no son cuentas: «12/03/2015 - 05/08/2024» (las de una
            # perrita que murió, 17/10) borraba la respuesta entera.
            if mala is None and _CUENTA.search(_FECHA.sub(" ", f)):
                mala = "número de cuenta o teléfono escrito por el modelo"
            if mala is None and inventa_datos_del_negocio(f):
                mala = "inventa datos del negocio (redes, enlaces, trayectoria)"
            if mala is None and _OTRO_NOMBRE.search(f):
                mala = "llama al negocio por un nombre que no es «Luna Joyas»"
            if mala is None and _PROMESAS_PROHIBIDAS.search(f):
                mala = "afirma un pago confirmado (solo lo confirma una persona)"
            if mala is None and promete_una_promocion(f, promociones):
                mala = "ofrece una promoción que no está activa (no hay; no se inventan)"
            if mala is None and DIRECCION_DE_CASA.search(f):
                # La casa de Lía (09/10): ni dirección, ni torre, ni apartamento.
                mala = "dirección de la casa de Lía (solo se dice el conjunto)"
            if mala is None:
                mala = _color_que_no_existe(f)
            if mala is None and borrador is not None:
                mala = _cantidad_que_no_es(f, borrador)
            if mala is None and borrador is not None:
                mala = _falso_segun_el_estado(f, borrador, estado_pedido)
            if mala:
                problemas.append(mala)
            else:
                buenas.append(f)
        if buenas or not linea.strip():
            lineas.append(" ".join(buenas))
    limpio = re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()
    if len(limpio) > LARGO_MAXIMO_MENSAJE:
        problemas.append("mensaje demasiado largo: recortado")
        limpio = limpio[:LARGO_MAXIMO_MENSAJE].rsplit(" ", 1)[0] + "…"
    return limpio, problemas
