"""El contrato del LLM. Lo ÚNICO que el modelo puede devolver.

════════════════════════════════════════════════════════════════════════════
POR QUÉ NO ES UNA LISTA DE INTENCIONES
════════════════════════════════════════════════════════════════════════════
El diseño anterior tenía un enum plano: SALUDO, CATALOGO, COTIZAR, ESTADO…
Funciona hasta que alguien pregunta «¿cuánto debo del segundo?». Entonces hace
falta CONSULTAR_SALDO. Y luego CONSULTAR_FECHA. Y CONSULTAR_ENVIO. En seis
meses hay ochenta intenciones, el modelo se confunde entre las parecidas, y
cada una nueva obliga a tocar el router.

Aquí se descompone en cuatro preguntas independientes:

    ¿QUÉ quiere hacer?   -> Acto       (once verbos, y no crecen)
    ¿SOBRE QUÉ?          -> Entidad    (las cosas del negocio)
    ¿QUÉ PARTE de eso?   -> Atributo   (estado, saldo, precio…)
    ¿CUÁL de ellas?      -> Referencia («el segundo», «ese»)

«¿Cuánto debo del segundo?» es CONSULTAR · PEDIDO · SALDO · ordinal 2. Cuatro
campos pequeños en vez de una etiqueta gigante. Y lo importante: una pregunta
que nadie previó —«¿de qué material es el segundo?»— ya está cubierta, porque
es CONSULTAR · PEDIDO · MATERIAL, y las tres piezas ya existen.

════════════════════════════════════════════════════════════════════════════
EL MODELO NO DECIDE NADA
════════════════════════════════════════════════════════════════════════════
Fíjate en lo que NO hay en esta estructura: no hay «acción», no hay «nodo»,
no hay «siguiente paso». El modelo describe lo que oyó; qué se hace con eso lo
decide `app.domain.acciones`, que es una tabla de Python.

Esa frontera es la que permite cambiar de Ollama a un modelo hospedado —o al
que exista dentro de tres años— sin tocar una línea de lógica de negocio: solo
cambia quién rellena esta estructura, no lo que se hace con ella.

Todos los campos de control son Enum cerrados, así que con decodificación
restringida (`format=<json_schema>`) es IMPOSIBLE que el modelo emita algo
fuera de la lista. La contención no es una súplica en el prompt.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, Field

from app.domain.historial import FiltroHistorico
from app.domain.personalizacion import ColorCircon


class Acto(str, Enum):
    """QUÉ quiere hacer. Once verbos, y la lista no debería crecer.

    Si algún día parece que falta uno, casi siempre es que en realidad falta
    una Entidad o un Atributo. Antes de agregar aquí, mirar allí.
    """

    SALUDAR = "SALUDAR"
    CONSULTAR = "CONSULTAR"  # quiere saber algo que ya existe
    COMPRAR = "COMPRAR"  # quiere algo nuevo
    MODIFICAR = "MODIFICAR"  # cambiar algo de lo que ya eligió
    AGREGAR = "AGREGAR"  # sumar algo
    ELIMINAR = "ELIMINAR"  # quitar algo
    CONFIRMAR = "CONFIRMAR"  # sí, dale, correcto
    CANCELAR = "CANCELAR"  # ya no lo quiero
    INFORMAR = "INFORMAR"  # me está dando un dato ("talla 8", "ya pagué")
    PREGUNTAR = "PREGUNTAR"  # duda general del negocio (garantía, envío…)
    RETOMAR = "RETOMAR"  # "sigamos", "volvamos al anillo"
    HUMANO = "HUMANO"  # quiere hablar con una persona
    CONVERSAR = "CONVERSAR"  # gracias, emojis, charla sin acción
    OTRO = "OTRO"


class Entidad(str, Enum):
    """SOBRE QUÉ. Son las cosas que existen en el negocio, no en el código."""

    PEDIDO = "PEDIDO"
    PRODUCTO = "PRODUCTO"
    PAGO = "PAGO"
    #: La foto de la transferencia. Es distinta de PAGO a propósito: «ya
    #: pagué» es una afirmación y un comprobante es un documento, y merecen
    #: respuestas distintas. La pone el lector de imágenes, no el modelo de
    #: texto.
    COMPROBANTE = "COMPROBANTE"
    ENVIO = "ENVIO"
    TALLA = "TALLA"
    COLOR = "COLOR"
    GRABADO = "GRABADO"
    IMAGEN = "IMAGEN"  # "quiero ver ejemplos"
    CLIENTE = "CLIENTE"
    NINGUNA = "NINGUNA"


class Atributo(str, Enum):
    """QUÉ PARTE de la entidad.

    Aquí es donde se absorbe la variedad que antes explotaba en intenciones.
    Agregar uno cuesta una línea y no toca el router.
    """

    ESTADO = "ESTADO"
    SALDO = "SALDO"
    TOTAL = "TOTAL"
    ABONO = "ABONO"
    PRECIO = "PRECIO"
    FECHA = "FECHA"
    COSTO_ENVIO = "COSTO_ENVIO"
    MATERIAL = "MATERIAL"
    GARANTIA = "GARANTIA"
    MEDIOS_DE_PAGO = "MEDIOS_DE_PAGO"
    TIEMPO = "TIEMPO"
    COMO_MEDIR = "COMO_MEDIR"
    CONTRAENTREGA = "CONTRAENTREGA"
    COLOR_DISPONIBLE = "COLOR_DISPONIBLE"
    #: «Está caro», «¿por qué vale tanto?». No es preguntar el precio: es
    #: dudar de que valga la pena, y se contesta contando qué lleva dentro.
    VALOR = "VALOR"
    #: «¿Es confiable?», «me da miedo pagar por adelantado». La objeción más
    #: cara del negocio, y la que más se calla.
    CONFIANZA = "CONFIANZA"
    #: «¿Y si no me queda?». Se pregunta antes de pagar, no después.
    AJUSTE = "AJUSTE"
    #: «¿Qué pasó con mi pedido de agosto?», «¿qué talla había pedido la vez
    #: pasada?». Un pedido del PASADO, que no está en el contexto normal y que
    #: hay que ir a buscar a propósito (ver `app/domain/historial.py`).
    HISTORIAL = "HISTORIAL"
    NINGUNO = "NINGUNO"


class TipoReferencia(str, Enum):
    """CÓMO señala la clienta de cuál habla.

    El modelo solo dice QUÉ TIPO de referencia usó. Convertirla en un id real
    es trabajo de `app.domain.referencias`, con la lista que se le mostró.
    Pedirle al modelo que «recuerde» cuál era el segundo es pedirle que haga
    de base de datos, y ahí es donde inventa.
    """

    NINGUNA = "NINGUNA"
    ORDINAL = "ORDINAL"  # "el primero", "el segundo"
    ULTIMO = "ULTIMO"  # "el último", "el más reciente"
    ANTERIOR = "ANTERIOR"  # "el anterior", "el de antes"
    ESE = "ESE"  # "ese", "ese pedido" -> el último mencionado
    OTRO = "OTRO"  # "el otro" -> el que NO es el último mencionado
    DESCRIPCION = "DESCRIPCION"  # "el anillo rosado", "el que ya enviaron"
    CODIGO = "CODIGO"  # "PED-2026-0417"


class Referencia(BaseModel):
    """A cuál se refiere. Sin resolver todavía."""

    tipo: TipoReferencia = TipoReferencia.NINGUNA
    #: Para ORDINAL: 1, 2, 3… Para las demás, se ignora.
    posicion: int | None = Field(default=None, ge=1, le=20)
    #: Para DESCRIPCION o CODIGO: el texto tal cual lo dijo. Se resuelve
    #: contra datos reales, nunca se usa como si fuera un identificador.
    texto: str | None = Field(default=None, max_length=80)


class DatosSueltos(BaseModel):
    """Información que la clienta dio de paso, sin que se la pidieran.

    «Quiero un anillo de dos huellitas talla 8» trae dos datos en una frase.
    Que quepan aquí es lo que permite no volver a preguntarlos — el defecto
    más irritante de cualquier bot.

    Ojo con los tipos: `talla` es un número y `colores` son Enum del
    muestrario. Un `str` libre aquí reabriría la puerta a fabricar un anillo
    de un color que no existe.
    """

    sku: str | None = None
    cantidad: int | None = Field(default=None, ge=1, le=50)
    huellitas: int | None = Field(default=None, ge=1, le=3)
    #: Otros anillos que pidió en el MISMO mensaje («uno de una huella y otro
    #: de dos»). No es un carrito: es una cola. Se atiende el primero y este
    #: campo es lo que impide que el resto se pierda en silencio.
    huellitas_extra: list[int] = Field(default_factory=list, max_length=4)
    talla: float | None = Field(default=None, ge=3, le=15)
    color_corazon: ColorCircon | None = None
    color_dedos: ColorCircon | None = None
    #: Colores que la clienta nombró SIN decir a qué parte van («morado» a
    #: secas). No son basura: son la mitad de una respuesta, y guardarlos es
    #: lo que permite preguntar «vi morado, ¿corazón o deditos?» en vez de
    #: repetir la pregunta entera como si no hubiera dicho nada.
    #: TODAS las huellitas que nombró en un mismo mensaje, en orden.
    #:
    #: «Corazón lila dedos rojos y el tercero verde corazón azul dedos» son
    #: DOS patitas. Leer solo la primera obliga a preguntarle otra vez algo
    #: que ya dijo, y es donde se nota que del otro lado hay una máquina.
    parejas: list[tuple[ColorCircon, ColorCircon]] = Field(
        default_factory=list, max_length=3
    )
    colores_sueltos: list[ColorCircon] = Field(default_factory=list, max_length=4)
    #: A qué parte del anillo se refiere, cuando nombra la parte y NO el color
    #: («para el corazón»). Es la otra mitad de la respuesta anterior: junto
    #: con un color suelto que quedó pendiente, forma una pareja completa.
    parte: str | None = Field(default=None, pattern="^(CORAZON|DEDOS)$")
    nombres: list[str] = Field(default_factory=list, max_length=5)
    sin_grabado: bool = False
    #: Dijo que la talla la manda después. Es una RESPUESTA, no una ausencia
    #: de respuesta: la clienta está en la calle, sin regla, y volver a
    #: preguntarle es la forma más segura de que no vuelva.
    talla_despues: bool = False
    ciudad: str | None = Field(default=None, max_length=60)
    #: A nombre de quién va el envío, y a qué dirección. Los llena la capa de
    #: expectativa cuando el bot acaba de preguntarlos: una dirección no se
    #: reconoce por su forma —«al lado del parque» es una dirección— sino
    #: porque es la respuesta a «¿cuál es tu dirección?».
    nombre_envio: str | None = Field(default=None, max_length=60)
    direccion: str | None = Field(default=None, max_length=120)
    #: Del modelo de visión, al leer la foto del anillo con la regla.
    diametro_mm: float | None = Field(default=None, ge=5, le=60)
    foto_clara: bool | None = None
    #: Qué medio de pago nombró («bancolombia», «nequi»). NO es un dato del
    #: anillo, y por eso queda fuera de `hay_algo()`: si contara, «bancolombia»
    #: dejaría de ser una pregunta del negocio y se intentaría anotar en el
    #: pedido. Se lee aparte, en la acción de explicar cómo pagar.
    medio_pago: str | None = Field(default=None, max_length=20)
    #: Llegó una foto de una transferencia. NO es un pago confirmado: es un
    #: papel. Lo pone el lector de imágenes, nunca el modelo de texto.
    comprobante: bool = False
    #: «Comencemos de 0», «quiero uno diferente». Pide una compra NUEVA y
    #: limpia: lo que estuviera a medias no se le pega. No es un dato del
    #: anillo, es una instrucción sobre cuál anillo.
    empezar_de_cero: bool = False
    monto_visto_cop: int | None = Field(default=None, ge=0, le=100_000_000)
    referencia_vista: str | None = Field(default=None, max_length=40)

    #: Campos que NO son información del anillo. `hay_algo()` responde a una
    #: sola pregunta —«¿este mensaje trae algo que anotar en el pedido?»— y
    #: estos dos no lo son.
    NO_SON_DATOS_DEL_ANILLO: ClassVar[tuple[str, ...]] = (
        "foto_clara",
        "medio_pago",
        "comprobante",
        "empezar_de_cero",
        "monto_visto_cop",
        "referencia_vista",
    )

    def hay_algo(self) -> bool:
        return any(
            v not in (None, [], False)
            for k, v in self.model_dump().items()
            if k not in self.NO_SON_DATOS_DEL_ANILLO
        )


class DatosDeTexto(BaseModel):
    """Lo que se puede sacar LEYENDO. El esquema que ve el modelo de texto.

    Es un subconjunto de `DatosSueltos` a propósito. Los campos que solo
    puede rellenar el lector de imágenes —el diámetro medido en una regla, el
    monto de un comprobante— no aparecen aquí, y esa ausencia hace dos cosas:

      1. El modelo de texto NO PUEDE inventarlos. Antes podía marcar
         `comprobante=True` leyendo «te mando el comprobante», y eso abría un
         caso de pago con una foto que nunca llegó.
      2. El esquema que viaja en cada prompt es más corto. Con un modelo de
         3B eso se nota en la latencia y en el acierto: cada campo de más es
         una decisión de más que puede salir mal.

    Los campos que Python saca solo (colores sueltos, medio de pago, cuántos
    anillos) tampoco están: los pisa el intérprete de todas formas, así que
    pedírselos al modelo era pagar por una respuesta que se iba a tirar.
    """

    sku: str | None = None
    cantidad: int | None = Field(default=None, ge=1, le=50)
    huellitas: int | None = Field(default=None, ge=1, le=3)
    talla: float | None = Field(default=None, ge=3, le=15)
    color_corazon: ColorCircon | None = None
    color_dedos: ColorCircon | None = None
    nombres: list[str] = Field(default_factory=list, max_length=5)
    sin_grabado: bool = False
    ciudad: str | None = Field(default=None, max_length=60)


class PropuestaDelModelo(BaseModel):
    """Lo ÚNICO que devuelve el modelo de TEXTO. Describe, no decide.

    Separado de `Interpretacion` porque no son lo mismo: esto es lo que dice
    un modelo, y aquello es lo que sabe el sistema después de sumarle lo que
    leyó Python y lo que vio el lector de imágenes.

    Tenerlos juntos hacía que cada campo interno nuevo acabara en el prompt,
    y que el modelo pudiera rellenar cosas que no había leído en ninguna
    parte.
    """

    acto: Acto
    entidad: Entidad = Entidad.NINGUNA
    atributo: Atributo = Atributo.NINGUNO
    referencia: Referencia = Field(default_factory=Referencia)
    datos: DatosDeTexto = Field(default_factory=DatosDeTexto)
    confianza: str = Field(default="MEDIA", pattern="^(ALTA|MEDIA|BAJA)$")

    model_config = {"use_enum_values": False}

    def a_interpretacion(self) -> Interpretacion:
        """Lo dicho por el modelo, ya dentro del tipo con el que trabaja todo."""
        return Interpretacion(
            acto=self.acto,
            entidad=self.entidad,
            atributo=self.atributo,
            referencia=self.referencia,
            datos=DatosSueltos(**self.datos.model_dump()),
            confianza=self.confianza,
        )


class RutaDeInterpretacion(BaseModel):
    """Por qué capa pasó el mensaje. Es observabilidad, no una decisión.

    capa:
      reglas   lo resolvió Python solo (atajos, expectativa, reglas decisivas)
      basico   hizo falta el modelo de la primera capa
      fuerte   se escaló al modelo potente
    """

    capa: str = "reglas"
    #: La regla o el motivo concreto: «atajo», «expectativa», «precio»,
    #: «historial», «modelo», «confianza_baja»…
    motivo: str = ""
    escalado: bool = False
    motivo_escalada: str = ""
    #: Lo que dijo el modelo ANTES de que Python lo corrigiera (acto·entidad).
    #: Si difiere del resultado, el turno cuenta como «acción corregida».
    dijo_el_modelo: str = ""
    corregido: bool = False
    #: Cuántos pedidos candidatos había al buscar en el historial.
    candidatos: int = 0


class Interpretacion(BaseModel):
    """Todo lo que se sabe del mensaje: lo leído, lo parseado y lo visto."""

    acto: Acto
    entidad: Entidad = Entidad.NINGUNA
    atributo: Atributo = Atributo.NINGUNO
    referencia: Referencia = Field(default_factory=Referencia)
    datos: DatosSueltos = Field(default_factory=DatosSueltos)
    #: BAJA obliga a confirmar antes de hacer nada que cueste dinero.
    confianza: str = Field(default="MEDIA", pattern="^(ALTA|MEDIA|BAJA)$")
    #: Qué tipo de foto venía, si venía alguna (`vision.TipoDeImagen`). Vacío
    #: cuando el mensaje era solo texto.
    foto: str = Field(default="", max_length=30)
    #: Lo que una persona tiene que confirmar. SOLO lo llena el lector de
    #: imágenes; lo que escriba el modelo de texto aquí se descarta, porque
    #: estas frases acaban en el panel de Lía y no pueden ser inventadas.
    notas: list[str] = Field(default_factory=list, max_length=6)
    #: Lo que la foto PARECE decir, en palabras para la clienta. Se usa para
    #: preguntárselo, nunca para guardarlo. Lo llena el lector de imágenes
    #: cuando cree haber entendido algo de lo que no nos podemos fiar.
    foto_dice: str = Field(default="", max_length=200)
    #: Qué dijo la frase del pedido del PASADO que busca (mes, color, código).
    #: Lo llena Python, nunca el modelo. `None` = no habla del pasado.
    historial: FiltroHistorico | None = None
    #: La referencia (nunca los bytes) de una foto que no se supo qué era y
    #: por la que se le va a preguntar a la clienta. La pone el lector.
    foto_pendiente: dict | None = None
    #: CÓMO se llegó a esta interpretación: qué capa respondió, si se escaló y
    #: por qué. No cambia lo que se hace; es para el registro de decisiones.
    ruta: RutaDeInterpretacion = Field(default_factory=lambda: RutaDeInterpretacion())

    model_config = {"use_enum_values": False}

    def resumen(self) -> str:
        """Una línea para el log. Es lo que se lee cuando algo sale raro."""
        partes = [self.acto.value]
        if self.entidad is not Entidad.NINGUNA:
            partes.append(self.entidad.value)
        if self.atributo is not Atributo.NINGUNO:
            partes.append(self.atributo.value)
        if self.referencia.tipo is not TipoReferencia.NINGUNA:
            ref = self.referencia.tipo.value.lower()
            if self.referencia.posicion:
                ref += f" {self.referencia.posicion}"
            partes.append(f"«{ref}»")
        if self.datos.hay_algo():
            traidos = [
                k
                for k, v in self.datos.model_dump().items()
                if v not in (None, [], False)
                and k not in self.datos.NO_SON_DATOS_DEL_ANILLO
            ]
            partes.append("+" + ",".join(traidos))
        return " · ".join(partes)
