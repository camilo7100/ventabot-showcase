"""La memoria de la conversación. ESTRUCTURADA, no un historial de mensajes.

════════════════════════════════════════════════════════════════════════════
POR QUÉ NO SE LE MANDA EL HISTORIAL AL MODELO
════════════════════════════════════════════════════════════════════════════
La forma fácil de que un bot «recuerde» es pegarle los últimos treinta
mensajes al prompt. Falla de tres maneras a la vez: cuesta tokens en cada
turno, se degrada según crece, y —lo grave— convierte un dato exacto («el
segundo pedido es el PED-2026-0456») en algo que el modelo tiene que
*deducir* leyendo. Y lo que se deduce, a veces se deduce mal.

Aquí la conversación recuerda como recuerda un sistema: en una tabla. Cuando
el bot muestra una lista, guarda qué había en cada posición. Después,
«el segundo» se resuelve buscando en esa tabla, no releyendo la conversación.

════════════════════════════════════════════════════════════════════════════
DOS MEMORIAS DISTINTAS, Y NO SE MEZCLAN
════════════════════════════════════════════════════════════════════════════
  · PERSISTENTE  -> clienta, pedidos, pagos. Vive en la base de datos, dura
                    años, y es la verdad. No está aquí.
  · CONVERSACIONAL -> esto. Qué se acaba de mostrar, de qué se está hablando,
                    qué quedó a medias. Dura días y se puede perder sin drama.

Este objeto se guarda en SQLite y NO en el checkpoint de LangGraph. Es una
decisión deliberada y mira al futuro: el día que el bot deje de ser reactivo y
empiece a escribir por su cuenta («llevas cuatro días sin mandarme la talla»),
ese trabajo programado va a necesitar leer los procesos abiertos de todas las
clientas, y un checkpoint solo se puede leer desde dentro de su conversación.

════════════════════════════════════════════════════════════════════════════
PROCESOS: LO QUE SUSTITUYE AL «PASO 1, PASO 2»
════════════════════════════════════════════════════════════════════════════
Antes había UN paso activo, un `str`. Por eso interrumpir era imposible: no
había dónde guardar la compra a medias mientras se contestaba otra cosa.

Un `Proceso` no es un paso: es una intención pendiente con información
incompleta. No tiene orden. Sabe qué le falta y ya. Puede haber varios a la
vez, y ninguno obliga a nada: si la clienta nunca vuelve a mencionarlo, se
queda ahí, y un día lo recoge un recordatorio.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.domain.models import new_id, now_utc

#: Cuánto vale una mención antes de considerarse vieja.
#:
#: Si la clienta escribe «el segundo» tres días después de haber visto la
#: lista, casi seguro no habla de aquella lista: habla de otra cosa, o se
#: acuerda mal. Resolverlo con datos viejos es peor que preguntar.
VIDA_MENCIONES_H = 24

#: Cuánto sigue vivo un proceso a medias. Doce días cubre la fabricación
#: entera (10-15 días) más el margen de una clienta que se demora en contestar.
VIDA_PROCESO_D = 12


def huella_de(texto: str) -> str:
    """Un resumen corto del texto, para comparar sin guardarlo entero."""
    # usedforsecurity=False: esto compara dos frases, no protege nada. Si
    # dos textos distintos colisionaran, el único efecto sería no variar una
    # pregunta una vez.
    return hashlib.sha1((texto or "").encode("utf-8"), usedforsecurity=False).hexdigest()[
        :12
    ]


class TipoProceso(str, Enum):
    """Qué quedó a medias. No son etapas: son cosas sin terminar."""

    COMPRA = "COMPRA"  # está armando un pedido
    DATOS_PEDIDO = "DATOS_PEDIDO"  # falta talla/color de un pedido ya pagado
    PAGO_REPORTADO = "PAGO_REPORTADO"  # dijo que pagó, falta comprobante
    ENVIO = "ENVIO"  # faltan los datos de envío


class Mencion(BaseModel):
    """Una cosa que el bot le mostró a la clienta, y en qué posición.

    Es la pieza que hace posible «el segundo» sin pedirle al modelo que se
    acuerde de nada.
    """

    posicion: int = Field(ge=1)
    tipo: str  # "PEDIDO" | "PRODUCTO"
    id: str
    #: Cómo se lo mostramos. Sirve para resolver «el anillo rosado» y para
    #: poder repetir la lista sin volver a consultar la base de datos.
    etiqueta: str = ""
    #: El código legible (PED-2026-0417). Va aparte de la etiqueta porque la
    #: etiqueta es lo que LEE la clienta y no lleva códigos; pero si ella
    #: escribe uno, hay que poder resolverlo sin buscar en la base de datos.
    codigo: str = ""


class Proceso(BaseModel):
    """Algo empezado y sin terminar. Con datos parciales y sin orden."""

    id: str = Field(default_factory=new_id)
    tipo: TipoProceso
    #: El pedido al que pertenece, cuando ya existe.
    pedido_id: str | None = None
    #: Lo que se sabe hasta ahora. Claves libres a propósito: cada tipo de
    #: proceso guarda lo suyo, y el dominio que lo entiende es el que valida.
    datos: dict = Field(default_factory=dict)
    #: Qué falta para poder cerrarlo. Lo calcula quien sabe del tema
    #: (`Personalizacion.falta()`), no este módulo.
    faltan: list[str] = Field(default_factory=list)
    creado: datetime = Field(default_factory=now_utc)
    tocado: datetime = Field(default_factory=now_utc)

    @property
    def completo(self) -> bool:
        return not self.faltan

    @property
    def pendientes(self) -> list[str]:
        """Lo que queda por PREGUNTAR. No es lo mismo que lo que falta.

        La talla sale de la lista cuando la clienta ya dijo que la manda
        después: volver a preguntársela sería no haberla escuchado. Pero
        sigue faltando para fabricar, y por eso `faltan` la conserva — el
        panel la ve y nadie manda el anillo al taller sin ella.

        Esa distinción es la que deja seguir la conversación sin perder el
        dato, y vive aquí para que el intérprete y el ejecutor no puedan
        tener dos ideas distintas de qué se está preguntando.
        """
        return [
            hueco
            for hueco in self.faltan
            if not (hueco == "talla" and self.datos.get("sin_talla"))
        ]

    def vivo(self, ahora: datetime | None = None) -> bool:
        ahora = ahora or datetime.now(UTC)
        tocado = self.tocado if self.tocado.tzinfo else self.tocado.replace(tzinfo=UTC)
        return ahora - tocado < timedelta(days=VIDA_PROCESO_D)

    def con(self, **datos) -> Proceso:
        """Devuelve una copia con datos nuevos. Nunca muta: el proceso viejo
        sigue existiendo hasta que alguien guarde el nuevo, lo que hace que un
        fallo a mitad de turno no deje el contexto a medio escribir."""
        limpios = {k: v for k, v in datos.items() if v is not None}
        return self.model_copy(
            update={"datos": {**self.datos, **limpios}, "tocado": now_utc()}
        )


class ContextoConversacional(BaseModel):
    """Todo lo que la conversación recuerda. Se guarda entero, es pequeño."""

    conversation_id: str
    #: La última lista que se le mostró. Se reemplaza entera cada vez: mezclar
    #: listas viejas y nuevas es la forma más rápida de que «el segundo»
    #: resuelva a algo de anteayer.
    menciones: list[Mencion] = Field(default_factory=list)
    menciones_en: datetime | None = None
    #: De qué se está hablando ahora mismo. Es lo que resuelve «ese» y lo que
    #: hace que «ya pagué» sepa de qué pedido, sin preguntar.
    foco_tipo: str | None = None
    foco_id: str | None = None
    #: El foco de ANTES. Resuelve «el otro» y «el anterior».
    foco_previo_id: str | None = None
    procesos: list[Proceso] = Field(default_factory=list)
    #: Qué se contestó la última vez, y cuántas veces seguidas lo mismo.
    #:
    #: Es lo único que hace falta para no mandar el MISMO mensaje dos veces.
    #: Repetir una pregunta palabra por palabra es la conducta más robótica
    #: que existe: le dice a la clienta «no te leí». Con esto, la segunda vez
    #: se pregunta distinto y la tercera se ofrece una persona.
    ultima_clave: str = ""
    veces: int = 0
    #: Huella del texto que salió. Con la clave sola, dos consultas de dos
    #: pedidos distintos parecían el mismo mensaje repetido; con el texto
    #: solo, cambiar un emoji burlaba el guardián. Hacen falta las dos.
    ultimo_texto: str = ""
    #: Cuántos mensajes lleva esta conversación. Sirve para variar las frases
    #: sin sortear nada: el mismo turno siempre da la misma variante, así que
    #: los tests siguen siendo deterministas y el bot deja de sonar igual.
    turnos: int = 0
    #: Lo que una persona tiene que confirmar antes de fabricar. Cada entrada
    #: es una frase corta para Lía, no para la clienta.
    #:
    #: Existe porque el bot NO se puede bloquear ante la duda: si el lector de
    #: imágenes no está seguro de una talla, se guarda lo que se vio, se anota
    #: aquí y la conversación sigue. Bloquear pierde la venta; inventar pierde
    #: el anillo. Anotar no pierde nada.
    revisar: list[str] = Field(default_factory=list)
    #: La ciudad de la clienta, en cuanto la dice.
    #:
    #: NO vive dentro de un `Proceso` a propósito. La ciudad no es un dato del
    #: anillo: es un dato de ELLA, y la dice cuando le da la gana —«hola, soy
    #: de Bogotá» antes de que exista ninguna compra abierta—. Guardarla solo
    #: en el proceso significaba tirarla en ese caso, que es el más frecuente.
    #:
    #: De aquí sale el flete de sus cotizaciones y la respuesta a «¿cuánto
    #: vale el envío?».
    ciudad: str | None = None
    #: Una foto que no se supo qué era y por la que se le preguntó a la
    #: clienta («¿es el comprobante o la foto de la talla?»). Se guarda la
    #: REFERENCIA del adjunto —nunca los bytes— para volver a mirarla con la
    #: pista correcta cuando conteste.
    foto_pendiente: dict | None = None
    #: Cuándo llegó la última foto. Es lo que permite contestar con la verdad
    #: a «ya te mandé la foto»: sí llegó, o no llegó ninguna.
    ultima_foto_en: datetime | None = None
    actualizado: datetime = Field(default_factory=now_utc)
    #: El pedido que va armando la asesora (`app.domain.asesora.Borrador`),
    #: guardado como dict para que este módulo no dependa de aquel.
    borrador: dict | None = None
    #: Los últimos mensajes de la conversación, de las dos partes, en orden.
    #: La asesora los lee para entender «sí», «ese» o «el del negrito».
    charla: list[dict] = Field(default_factory=list)
    #: Hasta cuándo calla el bot porque la está atendiendo una persona
    #: (`app.domain.atencion`). None = contesta el bot, como siempre.
    humano_hasta: datetime | None = None
    #: La clienta necesita a una persona (queja, lo pidió, caso raro). Queda
    #: hasta que Lía marca la conversación como Resuelta en Chatwoot.
    necesita_persona: bool = False
    #: Lo que ya se anotó en el CRM (notas privadas), para no repetirlo.
    crm_hecho: list[str] = Field(default_factory=list)
    #: Las NOTAS INTERNAS de Lía, escritas desde el panel al mover un pedido o
    #: al confirmar la talla (27/09). La clienta no las ve. La asesora las lee
    #: como contexto APARTE de la charla: nunca se confunden con lo que
    #: escribió ella. Cada una: {cuando, tipo, pedido, etapa, texto, autor}.
    notas_internas: list[dict] = Field(default_factory=list)
    #: Lo que escribió ella y NINGUNA IA pudo contestar (29/09): se reintenta en
    #: segundo plano hasta que alguna vuelva, y el turno siguiente lo incluye.
    #: {texto, media, desde, intentos, proximo}. None = nada pendiente.
    pendiente_ia: dict | None = None
    #: El contexto OPERATIVO del turno (`app.domain.operativo.Operativo`).
    #:
    #: NO se guarda: se reconstruye en cada turno desde la base de datos, que
    #: es la única que sabe qué pedidos siguen vivos. Viaja pegado al contexto
    #: para que el intérprete lo vea sin cambiar la firma de nadie.
    operativo: Any = Field(default=None, exclude=True)

    # -- menciones ----------------------------------------------------------

    def mostrar(self, items: list[tuple[str, str, str]]) -> ContextoConversacional:
        """Registra la lista que se le acaba de enseñar.

        `items` son (tipo, id, etiqueta) en el orden en que se muestran. La
        posición 1 es el primero que ve, no el índice 0 del programador: esa
        traducción se hace aquí una vez y no vuelve a aparecer.
        """
        menciones = [
            Mencion(posicion=i, tipo=t, id=x, etiqueta=e)
            for i, (t, x, e) in enumerate(items, start=1)
        ]
        return self.model_copy(
            update={
                "menciones": menciones,
                "menciones_en": now_utc(),
                "actualizado": now_utc(),
            }
        )

    def menciones_vigentes(self, ahora: datetime | None = None) -> list[Mencion]:
        """Las menciones, si todavía valen. Vacío si son viejas."""
        if not self.menciones or self.menciones_en is None:
            return []
        ahora = ahora or datetime.now(UTC)
        cuando = (
            self.menciones_en
            if self.menciones_en.tzinfo
            else self.menciones_en.replace(tzinfo=UTC)
        )
        if ahora - cuando > timedelta(hours=VIDA_MENCIONES_H):
            return []
        return self.menciones

    # -- foco ---------------------------------------------------------------

    def enfocar(self, tipo: str, id_: str) -> ContextoConversacional:
        """Marca de qué se está hablando. Conserva el foco anterior.

        Guardar el previo es lo único que hace resoluble «el otro», y cuesta
        un campo.
        """
        if self.foco_id == id_:
            return self.model_copy(update={"actualizado": now_utc()})
        return self.model_copy(
            update={
                "foco_previo_id": self.foco_id,
                "foco_tipo": tipo,
                "foco_id": id_,
                "actualizado": now_utc(),
            }
        )

    # -- lo que tiene que mirar una persona ---------------------------------

    def anotar_revision(self, motivo: str) -> ContextoConversacional:
        """Deja constancia de algo que hay que confirmar. Nunca duplica.

        No corta la conversación ni escala: es una nota para el panel. La
        diferencia con `escalar` es el tiempo — escalar es «atiende esto
        ahora», esto es «antes de fabricar, mira esto».

        Tampoco duplica lo que solo se PARECE: el modelo vuelve a anotar el
        mismo hecho cada turno con otras palabras, y en un repaso quedaron tres
        notas para decir que había pagado con el pedido incompleto (20/09). Una
        lista donde tres avisos dicen lo mismo se deja de mirar, y el día que
        haya uno de verdad se pierde entre el ruido.
        """
        if not motivo or motivo in self.revisar:
            return self
        if _casi_igual(motivo, self.revisar):
            return self
        return self.model_copy(
            update={"revisar": [*self.revisar, motivo], "actualizado": now_utc()}
        )

    # -- no repetirse -------------------------------------------------------

    def registrar_salida(
        self, clave: str, huella: str = "", *, avanzo: bool = False
    ) -> ContextoConversacional:
        """Apunta qué se acaba de contestar. `clave` es semántica, no el texto.

        Semántica y no el texto porque lo que hay que detectar es «vuelvo a
        preguntar lo mismo», no «vuelvo a escribir los mismos caracteres».
        Con el texto, cambiar un emoji bastaría para volver a empezar.

        ════════════════════════════════════════════════════════════════════
        `avanzo`: SI ELLA CONTESTÓ ALGO, LA CUENTA VUELVE A CERO
        ════════════════════════════════════════════════════════════════════
        Sin esto, la cuenta de insistencias solo subía, y una conversación real
        se murió por eso. Faltaba la cantidad de huellitas; ella fue dando el
        grabado, su nombre, la ciudad y la dirección —contestando, uno por
        uno— y cada turno subía la cuenta un punto más, hasta que el bot pasó a
        «mejor te paso con una personita» y contestó eso mismo a TODO lo demás,
        incluida una pregunta nueva sobre el tiempo de entrega.

        Insistir tres veces y rendirse está bien cuando no nos entendemos. Pero
        una clienta que trae un dato nuevo no es una clienta que no contesta:
        es una clienta que está comprando.
        """
        if not clave:
            return self
        self = self.model_copy(update={"turnos": self.turnos + 1})
        if clave == self.ultima_clave and not avanzo:
            return self.model_copy(
                update={
                    "veces": self.veces + 1,
                    "ultimo_texto": huella,
                    "actualizado": now_utc(),
                }
            )
        return self.model_copy(
            update={
                "ultima_clave": clave,
                "veces": 0,
                "ultimo_texto": huella,
                "actualizado": now_utc(),
            }
        )

    # -- procesos -----------------------------------------------------------

    def abiertos(
        self, tipo: TipoProceso | None = None, ahora: datetime | None = None
    ) -> list[Proceso]:
        """Los procesos que siguen vivos, del más reciente al más viejo.

        El orden importa: cuando llega un dato suelto («talla 8») y hay que
        adivinar a cuál pertenece, el candidato natural es el que se tocó
        hace un minuto, no el de la semana pasada.
        """
        # Un proceso de un pedido ACTIVO no caduca: el anillo sigue en el
        # taller aunque la conversación lleve veinte días callada. Qué pedidos
        # están activos lo sabe el contexto operativo, que sale de la base de
        # datos (ver `app/domain/operativo.py`).
        activos = (
            self.operativo.ids_activos if self.operativo is not None else frozenset()
        )
        # Desempate por POSICIÓN: `guardar_proceso` deja al final el último
        # guardado. Sin esto, dos procesos creados en el mismo turno pueden
        # llevar el mismo `tocado` (en un equipo rápido pasa), el orden estable
        # dejaba primero al más VIEJO y un «talla 8» se iba al anillo cerrado.
        vivos = [
            (i, p)
            for i, p in enumerate(self.procesos)
            if (p.vivo(ahora) or (p.pedido_id or p.datos.get("pedido_id")) in activos)
            and (tipo is None or p.tipo is tipo)
        ]
        return [
            p
            for _, p in sorted(vivos, key=lambda ip: (ip[1].tocado, ip[0]), reverse=True)
        ]

    def guardar_proceso(self, proceso: Proceso) -> ContextoConversacional:
        """Agrega o reemplaza un proceso por id."""
        otros = [p for p in self.procesos if p.id != proceso.id]
        return self.model_copy(
            update={"procesos": [*otros, proceso], "actualizado": now_utc()}
        )

    def cerrar_proceso(self, proceso_id: str) -> ContextoConversacional:
        return self.model_copy(
            update={
                "procesos": [p for p in self.procesos if p.id != proceso_id],
                "actualizado": now_utc(),
            }
        )

    def limpiar(self, ahora: datetime | None = None) -> ContextoConversacional:
        """Tira lo caducado. Se llama al cargar, no con un temporizador.

        Sin esto, el contexto de una clienta de hace un año seguiría creciendo
        y «el segundo» resolvería a un pedido entregado en marzo.
        """
        return self.model_copy(
            update={
                "procesos": [p for p in self.procesos if p.vivo(ahora)],
                "menciones": self.menciones_vigentes(ahora),
            }
        )


#: Cuánto se tienen que parecer dos notas para que sea la misma. Alto a
#: propósito: perder un aviso de verdad es peor que repetir uno.
PARECIDO_DE_UNA_NOTA = 0.72


def _casi_igual(nota: str, anteriores: list[str]) -> bool:
    """¿Ya hay una nota que dice casi esto?"""
    from difflib import SequenceMatcher

    nuevo = " ".join(nota.lower().split())
    for vieja in anteriores:
        viejo = " ".join((vieja or "").lower().split())
        if SequenceMatcher(None, nuevo, viejo).ratio() >= PARECIDO_DE_UNA_NOTA:
            return True
    return False
