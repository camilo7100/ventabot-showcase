"""Lo que se puede leer de una foto. El contrato del lector de imágenes.

════════════════════════════════════════════════════════════════════════════
POR QUÉ LAS IMÁGENES TIENEN SU PROPIO MODELO
════════════════════════════════════════════════════════════════════════════
El modelo de texto y el de visión resuelven problemas distintos y se eligen
con criterios distintos. Meterlos en el mismo sitio obliga a que el que lee
«quiero un anillo de dos huellitas» sea también el que mira una regla — y el
día que uno de los dos se quede corto, cambiarlo mueve el otro.

Aquí están separados de verdad: `VisionPort` es un puerto propio, con su
propio modelo configurable (`OLLAMA_VISION_MODEL`) y su propio esquema. Se
puede apagar, cambiar por uno de pago, o sustituir por una persona, sin tocar
una línea de la conversación.

════════════════════════════════════════════════════════════════════════════
LO QUE EL MODELO PUEDE DECIR, Y LO QUE NO
════════════════════════════════════════════════════════════════════════════
El modelo LEE: qué tipo de foto es, qué número aparece, qué color se ve, si
la foto está clara. Todo lo demás lo decide Python:

    · de milímetros a talla        -> `tallas.medir()`, una tabla
    · de «lo vi» a «lo guardamos»  -> la confianza, aquí abajo
    · de duda a revisión humana    -> `Hallazgo.revisar`

Esa división es la misma de todo el proyecto y aquí importa más que en
ningún otro sitio, porque una foto mal leída se convierte en un anillo de
plata de la talla equivocada.

════════════════════════════════════════════════════════════════════════════
LA REGLA QUE MANDA SOBRE TODAS
════════════════════════════════════════════════════════════════════════════
    Si se entiende con seguridad: se guarda.
    Si no: se guarda LO QUE SE VIO, se marca para revisión y la
    conversación SIGUE.

Nunca se bloquea y nunca se inventa. Bloquear pierde la venta; inventar
pierde el anillo. Anotar y seguir no pierde nada, y este negocio revisa a
mano todas las conversaciones que llegan a transacción de todas formas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field

from app.domain.personalizacion import ColorCircon
from app.domain.tallas import medir


class TipoDeImagen(str, Enum):
    """Qué manda la gente. Salen de mirar las conversaciones reales de Lía.

    `OTRA` no es un fallo: es la respuesta honesta cuando la foto no es
    ninguna de las que sabemos aprovechar, y provoca una respuesta amable en
    vez de un silencio.
    """

    COMPROBANTE = "COMPROBANTE"  # captura de una transferencia
    ANILLO_CON_REGLA = "ANILLO_CON_REGLA"  # para sacar la talla
    CIRCONES_SENALADOS = "CIRCONES_SENALADOS"  # el muestrario con algo marcado
    MASCOTA = "MASCOTA"  # la foto del peludito
    OTRA = "OTRA"


class LecturaDeImagen(BaseModel):
    """Lo ÚNICO que devuelve el modelo de visión. Describe, no decide.

    Todos los campos menos `tipo` y `seguro` son opcionales a propósito: una
    foto de un comprobante no tiene diámetro, y una regla no tiene monto.
    Pedirle al modelo que rellene lo que no ve es pedirle que invente.
    """

    tipo: TipoDeImagen = TipoDeImagen.OTRA
    #: ¿El modelo está seguro de lo que dice? Es la palanca que decide si un
    #: dato se usa o se manda a revisar. Se le pregunta explícitamente porque
    #: un modelo pequeño mirando una regla torcida acierta la mitad de las
    #: veces, y saber cuál mitad vale más que acertar un poco más.
    seguro: bool = False

    # -- comprobante --------------------------------------------------------
    monto_cop: int | None = Field(default=None, ge=0, le=100_000_000)
    referencia: str | None = Field(default=None, max_length=40)
    banco: str | None = Field(default=None, max_length=30)

    # -- anillo contra una regla -------------------------------------------
    #: El diámetro INTERNO que se lee en la regla. En milímetros porque es lo
    #: que está impreso; la talla la calcula `tallas.medir()`.
    #: El diámetro que se lee en la regla. El mínimo es 0.5 y no 5 a
    #: propósito: la regla está impresa en CENTÍMETROS y el modelo devuelve
    #: «2.0» la mitad de las veces. Rechazarlo perdía la lectura entera por
    #: una unidad; ahora se acepta y `_a_milimetros` la convierte.
    diametro_mm: float | None = Field(default=None, ge=0.5, le=60)
    foto_clara: bool | None = None

    # -- muestrario con un color señalado ----------------------------------
    #: ¿Hay de verdad una MARCA en la foto —un círculo, una flecha, un dedo
    #: señalando— o solo se ven las bolsitas?
    #:
    #: Sale de medir: con las fotos del muestrario a secas, sin nada marcado,
    #: el modelo contestaba «CIRCONES_SENALADOS, seguro» y se inventaba dos
    #: colores. Tres de tres. Preguntarle por la marca aparte es lo que
    #: separa «veo colores» de «veo que señaló uno».
    hay_marca: bool = False
    color_corazon: ColorCircon | None = None
    color_dedos: ColorCircon | None = None

    #: Qué se ve, en una frase. No se le enseña a la clienta: va al panel,
    #: para que quien revise entienda de qué foto se trataba sin abrirla.
    descripcion: str = Field(default="", max_length=200)


@dataclass
class Hallazgo:
    """Lo que se saca en limpio de una foto, ya decidido.

    Separa dos cosas que la `LecturaDeImagen` mezcla: lo que se GUARDA y lo
    que hay que REVISAR. Puede haber las dos a la vez —una talla que se usa
    pero que alguien confirma— y ese caso es el más común de todos.
    """

    tipo: TipoDeImagen
    #: Datos aprovechables, con las claves que entiende el proceso de compra.
    datos: dict = field(default_factory=dict)
    #: Frases para el panel. Nunca se le muestran a la clienta.
    revisar: list[str] = field(default_factory=list)
    #: Qué contarle a ella. Vacío = que lo decida el flujo normal.
    descripcion: str = ""
    #: Lo que la foto PARECE decir, en palabras para la clienta.
    #:
    #: Se usa para preguntar, no para guardar. Cuando el modelo cree haber
    #: visto unos colores señalados y no nos fiamos, se le enseña lo que
    #: creímos entender y se le pide que lo escriba: la información no se
    #: pierde, no se inventa nada, y su respuesta en texto SÍ es de fiar.
    para_preguntar: str = ""

    @property
    def aporta(self) -> bool:
        return bool(self.datos)


#: Cuando el modelo dice que no está seguro, ¿se tira el dato?
#:
#: No. Se guarda igual y se marca. Es lo contrario de lo que haría un sistema
#: cauto, y es deliberado: aquí una persona revisa TODAS las conversaciones
#: que llegan a transacción antes de fabricar, así que un dato dudoso guardado
#: y marcado es información; un dato tirado es una pregunta más que hacerle a
#: la clienta, y cada pregunta de más pierde gente.
GUARDAR_AUNQUE_DUDE = True


def entender(lectura: LecturaDeImagen) -> Hallazgo:
    """De lo que el modelo vio a lo que el sistema hace. Python puro.

    Aquí no hay red, ni modelo, ni base de datos: es una función que se prueba
    en microsegundos y que contiene toda la política. Si mañana hay que ser
    más estricto con las tallas dudosas, se cambia aquí y en ningún otro sitio.
    """
    if lectura.tipo is TipoDeImagen.COMPROBANTE:
        return _comprobante(lectura)
    if lectura.tipo is TipoDeImagen.ANILLO_CON_REGLA:
        return _talla(lectura)
    if lectura.tipo is TipoDeImagen.CIRCONES_SENALADOS:
        return _colores(lectura)
    if lectura.tipo is TipoDeImagen.MASCOTA:
        return Hallazgo(tipo=lectura.tipo, descripcion=lectura.descripcion)
    return Hallazgo(tipo=TipoDeImagen.OTRA, descripcion=lectura.descripcion)


def _comprobante(lectura: LecturaDeImagen) -> Hallazgo:
    """Un comprobante NUNCA confirma un pago. Solo dice que llegó uno.

    Da igual que el modelo lea el monto perfectamente: una captura de pantalla
    se edita en treinta segundos. Lo que hace esto es dejar constancia y sacar
    a la clienta del limbo de «¿lo recibieron?», que es donde se pierden las
    ventas — no aprobar nada.
    """
    hallazgo = Hallazgo(
        tipo=lectura.tipo,
        datos={"comprobante": True},
        descripcion=lectura.descripcion,
    )
    if lectura.monto_cop:
        hallazgo.datos["monto_visto_cop"] = lectura.monto_cop
    if lectura.referencia:
        hallazgo.datos["referencia_vista"] = lectura.referencia
    if lectura.banco:
        hallazgo.datos["banco_visto"] = lectura.banco

    detalle = ", ".join(
        parte
        for parte in (
            f"${lectura.monto_cop:,.0f}".replace(",", ".") if lectura.monto_cop else "",
            lectura.banco or "",
            f"ref. {lectura.referencia}" if lectura.referencia else "",
        )
        if parte
    )
    hallazgo.revisar.append(
        "Mandó un comprobante" + (f" ({detalle})" if detalle else "") + ": verificar "
        "el pago en la cuenta antes de mandar a producción."
    )
    return hallazgo


#: Por debajo de esto, el número que devolvió el modelo son CENTÍMETROS.
#:
#: Ningún anillo de dedo mide 2 mm, y las reglas están impresas en cm: el
#: modelo lee «2.0» y lo escribe tal cual. Convertirlo es aritmética, no
#: adivinar — y sin esto la lectura se perdía entera por un error de unidad.
UMBRAL_CENTIMETROS = 5.0


def _a_milimetros(medida: float) -> float:
    return medida * 10 if medida < UMBRAL_CENTIMETROS else medida


def _talla(lectura: LecturaDeImagen) -> Hallazgo:
    """El anillo contra la regla. El número lo lee el modelo; la talla, la tabla.

    ════════════════════════════════════════════════════════════════════════
    LA TALLA DE UNA FOTO SIEMPRE SE CONFIRMA
    ════════════════════════════════════════════════════════════════════════
    No importa lo seguro que diga estar el modelo. Midiendo con las fotos
    reales dijo «seguro» y «foto clara» en TODAS, incluidas las que leyó mal
    — y una talla equivocada es un anillo que no entra, fundido y pagado.

    Fiarse de la autoconfianza de un modelo pequeño es fiarse del único
    número que no puede calibrar. Así que la talla se usa (la conversación no
    se para nunca) y se marca (Lía la confirma antes de fabricar). Cuesta un
    vistazo en el panel y ahorra un anillo.
    """
    if lectura.diametro_mm is None:
        return Hallazgo(
            tipo=lectura.tipo,
            revisar=[
                "Mandó la foto del anillo con la regla pero no se pudo leer la "
                "medida: tomar la talla a mano."
            ],
            descripcion=lectura.descripcion,
        )

    milimetros = _a_milimetros(lectura.diametro_mm)
    medicion = medir(milimetros, foto_clara=bool(lectura.foto_clara))
    unidad = ", venía en cm" if milimetros != lectura.diametro_mm else ""

    hallazgo = Hallazgo(
        tipo=lectura.tipo,
        datos={
            "talla": medicion.talla,
            "diametro_mm": round(milimetros, 1),
            # SIEMPRE. Ver el docstring de arriba.
            "talla_revisar": True,
            "talla_motivo": medicion.motivo
            or "medida sacada de una foto: confirmar antes de fabricar",
        },
        descripcion=lectura.descripcion,
    )
    aviso = f" — {medicion.motivo}" if medicion.motivo else ""
    hallazgo.revisar.append(
        f"Talla {medicion.etiqueta} sacada de la foto "
        f"({milimetros:.1f} mm{unidad}) — CONFIRMAR{aviso}"
    )
    return hallazgo


def _colores(lectura: LecturaDeImagen) -> Hallazgo:
    """El muestrario con un círculo encima. La lectura más difícil de todas.

    ════════════════════════════════════════════════════════════════════════
    AQUÍ NO SE GUARDA NADA: SE PREGUNTA
    ════════════════════════════════════════════════════════════════════════
    Catorce bolsitas de colores parecidos, una foto de móvil y una marca
    hecha con el dedo. Midiendo con las fotos reales del muestrario —sin nada
    señalado— el modelo contestó «CIRCONES_SENALADOS, seguro» y se inventó
    dos colores. Tres veces de tres.

    Así que lo que ve NO entra en el pedido: entra en la PREGUNTA. Se le
    enseña a la clienta lo que creímos entender y se le pide que lo escriba.
    Su respuesta en texto la lee un parser determinista que no se inventa
    colores, y ahí sí se guarda.

    No se pierde nada —lo visto queda en la nota del panel— y no se funde un
    anillo del color que no era. Preguntar cuesta un mensaje; equivocarse
    cuesta el anillo, el envío y la clienta.
    """
    vistos = [c for c in (lectura.color_corazon, lectura.color_dedos) if c]

    if not (lectura.hay_marca and lectura.seguro and vistos):
        return Hallazgo(
            tipo=lectura.tipo,
            revisar=[
                "Mandó una foto del muestrario y no se pudo identificar qué "
                "señaló: se le pidieron los colores por escrito."
            ],
            descripcion=lectura.descripcion,
        )

    from app.domain.personalizacion import NOMBRE_COLOR

    partes = []
    if lectura.color_corazon:
        partes.append(f"el *corazón* en {NOMBRE_COLOR[lectura.color_corazon]}")
    if lectura.color_dedos:
        # «en morado» y no «morados»: así no hay que pluralizar catorce
        # colores, y «azul rey» tampoco se rompe.
        partes.append(f"los *deditos* en {NOMBRE_COLOR[lectura.color_dedos]}")
    dice = " y ".join(partes)

    return Hallazgo(
        tipo=lectura.tipo,
        revisar=[
            f"En la foto del muestrario parecía señalar {dice} — se le pidió "
            f"que lo confirmara por escrito."
        ],
        descripcion=lectura.descripcion,
        para_preguntar=(
            f"Me parece que señalaste {dice} 👀 ¿Es así? Escríbemelo tal cual "
            f"y lo dejo anotado ✨"
        ),
    )
