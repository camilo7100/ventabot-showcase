"""Las clientas de la prueba de verdad (04/10).

Cada una es una conversación ENTERA, con su forma de escribir (bien escrito,
con errores, dictado por voz, en mayúsculas, a ráfagas) y su camino. Entre
todas recorren cada etapa del bot: apertura, talla (dicha, con la regla, con
una medida, sin saberla), cantidad, colores, grabado (con y sin, con fecha),
nombre, resumen, cambios después del resumen, cuentas, comprobante (bien, con
el valor de la transferencia, en PDF, antes de tiempo, «ya transferí»), lo
que hace Lía (talla, abono, anillo listo, saldo, despacho), datos de envío,
varios anillos, la cadena, la vitrina del catálogo, objeciones y una queja.

Dos clases de clienta:

- **Compradora** (`compradora=…`): sabe sus datos y CONTESTA a lo que el bot
  pregunta, en el orden en que el bot pregunte (`scripts/verdad/compradora.py`).
  Así se prueba el flujo de verdad y no un orden fijo. `pasos` son lo que
  escribe antes (su primer mensaje) y `final` lo que pasa después del pago.
- **Con libreto** (solo `pasos`): cuando el orden ES la prueba (regatear, una
  queja, pagar antes de terminar, la vitrina).

`etapa` es para el marcador; `espera` es lo que se revisa en ese paso además
de las reglas de siempre. Los números son 5700000000xx: el embudo los ignora.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scripts.verdad.compradora import Compradora
from scripts.verdad.revisiones import (
    Revision,
    borrador,
    dice,
    entre_comillas_si_lo_nombra,
    manda,
    no_dice,
    no_manda,
    no_pide,
    no_pregunta,
    pedido_en,
    pregunta,
    sin_pedido,
)


@dataclass
class Paso:
    etapa: str
    texto: str | None = None
    foto: str | None = None
    #: Varios mensajes seguidos (segundo y medio entre uno y otro): el bot
    #: tiene que contestar UNA vez, a todo junto.
    rafaga: tuple[str, ...] = ()
    #: Lo que hace Lía en el panel: «confirmar_talla:7», «verificar_abono»,
    #: «anillo_listo», «verificar_saldo», «despachar».
    lia: str | None = None
    #: Escribe desde un producto de la vitrina de WhatsApp (SKU).
    producto: str | None = None
    espera: tuple[Revision, ...] = ()
    #: Lo que este paso cuenta de ella (además de lo que sale de la foto).
    pidio_cadena: bool = False
    pidio_cuentas: bool = False
    dijo_que_pago: bool = False
    medida: bool = False


@dataclass
class Clienta:
    clave: str
    nombre: str  # el de su perfil de WhatsApp
    numero: str
    como_escribe: str
    pasos: list[Paso] = field(default_factory=list)
    compradora: Compradora | None = None
    final: list[Paso] = field(default_factory=list)
    #: Si su forma de escribir es a ráfagas: cada respuesta con «|» se parte.
    rafagas: bool = False
    pidio_cadena: bool = False


def P(etapa: str, texto: str | None = None, *espera: Revision, **kw) -> Paso:
    """Un paso: `P("talla", "talla 6", revision, …)` o con `espera=(…)`."""
    kw["espera"] = tuple(espera) + tuple(kw.get("espera", ()))
    return Paso(etapa, texto, **kw)


APERTURA = (dice("bienvenida a lia accesorios"), manda("presentacion"), pregunta())
RECIBIDO = (dice("recibido"), pedido_en("EN_REVISION_PAGO"))
DESPUES_DEL_PAGO = [
    P(
        "despues del abono",
        "¿Y cuánto se demora en estar listo?",
        dice("15", alguna=True),
    ),
    P(
        "lia abono",
        lia="verificar_abono",
        espera=(pedido_en("EN_PRODUCCION"), dice("taller")),
    ),
    P(
        "anillo listo",
        lia="anillo_listo",
        espera=(pedido_en("ESPERANDO_SALDO"), dice("140.000", "cedula")),
    ),
    P(
        "datos de envio",
        "Bogotá\nLaura Gómez Pérez\n1020304050\n3001234567\n"
        "Calle 45 # 12-30 apto 301, Chapinero",
    ),
    P("saldo", foto="comprobante_saldo_140000", espera=RECIBIDO),
    P("lia saldo", lia="verificar_saldo", espera=(pedido_en("SALDO_PAGADO"),)),
    P("despacho", lia="despachar", espera=(pedido_en("DESPACHADO"),)),
]

CLIENTAS: list[Clienta] = [
    Clienta(
        "laura",
        "Laura",
        "570000000101",
        "bien escrito, despacio, la venta entera hasta el despacho",
        [P("apertura", "Hola, buenas tardes. Quiero información del anillo", *APERTURA)],
        Compradora(
            talla=["Mi talla es la 6"],
            cantidad=["Quiero el de una huellita"],
            colores=["Corazón rosado y los deditos blancos"],
            grabado=["Que diga Luna"],
            nombre="Laura Gómez",
            en_el_resumen=("talla: 6", "luna"),
        ),
        final=DESPUES_DEL_PAGO,
    ),
    Clienta(
        "paula_04_10",
        "Lía",
        "570000000102",
        "la conversación real del 04/10: dictado por voz, corto, comprobante con el "
        "valor de la transferencia y el nombre tapado",
        [P("apertura", "Hola", *APERTURA)],
        Compradora(
            talla=["Gamma seis"],
            cantidad=["Una"],
            colores=["Dedos lila y corazón zafiro"],
            grabado=["Morita 21/09/23"],
            nombre="Lía Vasquez",
            confirma="Si",
            paga_con="comprobante_59700",
            en_el_resumen=("talla: 6", "morita 21/09/23"),
        ),
        final=[
            P("despues del abono", "Como así ?", no_dice("pense que", "otra foto")),
        ],
    ),
    Clienta(
        "laura_sin_anillos",
        "Laura",
        "570000000119",
        "la conversación real del 05/10: pide la guía y no tiene anillos para medir; "
        "se mide el dedo con un papel (con el video, Camilo 13/10; antes la joyería) "
        "y vuelve con la talla",
        [
            P("apertura", "¡Hola! Quiero más información sobre el anillo", *APERTURA),
            P("talla", "Me compartes la guía por favor", manda("medir_talla_guia")),
            P(
                "sin anillos",
                "Es que no tengo anillos 🫣",
                dice("tira de papel", "centimetros"),
                manda("medir_talla_dedo"),
                no_manda("medir_talla_guia"),
                no_dice("joyeria"),
            ),
        ],
        Compradora(
            talla=["Ya me medí con el papelito y soy talla 7"],
            cantidad=["1 huellita"],
            colores=["Toda en rosado"],
            grabado=["Luna"],
            nombre="Laura Contreras",
            en_el_resumen=("talla: 7", "luna"),
        ),
    ),
    Clienta(
        "vale_dorado",
        "Valentina",
        "570000000120",
        "la pregunta real del 05/10: «¿solo en plata? ¿no hay dorado?» justo después "
        "de la presentación; después compra normal (y pide el corazón dorado: la piedra)",
        [
            P("apertura", "¡Hola! Quiero más información sobre el anillo", *APERTURA),
            P(
                "solo en plata",
                "Solo en plata? No hay dorado?",
                dice("solo en plata", "se pelan"),
                no_dice("si manejamos dorado", "te lo podemos banar"),
                pregunta(),
            ),
        ],
        Compradora(
            talla=["talla 8"],
            cantidad=["Una"],
            colores=["el corazón dorado y los deditos blancos"],
            grabado=["Simba"],
            nombre="Valentina Ríos",
            en_el_resumen=("talla: 8", "simba"),
        ),
    ),
    Clienta(
        "sara_espera_a_lia",
        "Sara",
        "570000000122",
        "la charla real de Laura (06/10): manda la foto de la regla, escoge todo y "
        "queda esperando que Lía confirme la talla; dice «Gracias» y «ok»: el bot ya "
        "no le pregunta nada (ni extras, ni «¿te parece?»)",
        [
            P("apertura", "Hola, quiero info del anillo", *APERTURA),
            P("talla", "no sé mi talla", manda("medir_talla_guia")),
            P("regla", foto="regla"),
            P("cantidad", "una huellita"),
            P("colores", "corazón blanco y deditos lila"),
            P("grabado", "Bombom", entre_comillas_si_lo_nombra("Bombom")),
            P("nombre", "Sara Gómez"),
            P("gracias", "Gracias 🥰", no_pregunta()),
            P("ok", "ok perfecto", no_pregunta()),
        ],
    ),
    Clienta(
        "erika_cadena",
        "Erika",
        "570000000123",
        "la charla real del 07/10: ve los precios y pregunta por la cadena con 3 "
        "huellitas: la información de la cadena va de una (lleva UNA huellita)",
        [
            P("apertura", "¿Qué precio tiene el anillo? 💍🐾", *APERTURA),
            P(
                "cadena",
                "Y la cadena con 3 huellitas",
                manda("cadena_1"),
                dice("una sola huellita", "una huellita", alguna=True),
                no_dice("te cuente", "te mando la informacion"),
                pidio_cadena=True,
            ),
        ],
        pidio_cadena=True,
    ),
    Clienta(
        "monica_escribe_corto",
        "Mónica",
        "570000000124",
        "la charla real del 07/10, mal escrita y corta: «creo que soy 7», «De una», "
        "«Ese rosa está muy lindo»; con las cuentas dice «gracias» y «mañana le "
        "consigno»: no se le re-confirma nada ni se le insiste",
        [
            P("apertura", "¿Qué precio tiene el anillo? 💍🐾", *APERTURA),
            P("talla", "La verdad creo que soy 7", borrador(talla=7.0)),
            P("cantidad", "De una", borrador(cantidad=1), no_dice("1, 2 o 3")),
            P("colores", "Ese rosa está muy lindo", no_dice("combinar")),
            P("grabado", "Campanita y Dulce"),
            P("nombre", "Mónica Quintero"),
            P("resumen", "Perfecto"),
            P("gracias", "Tan bella muchas gracias", no_pregunta()),
            P(
                "pospone",
                "Yo el día de mañana le estaré consignando",
                no_pregunta(),
                pedido_en("ESPERANDO_ANTICIPO"),
            ),
        ],
    ),
    Clienta(
        "andrea_regla",
        "Andrea",
        "570000000103",
        "no sabe su talla: pide la guía, manda la foto de la regla y Lía la confirma; "
        "paga diciendo «ya te transferí»",
        [P("apertura", "hola!! info porfa", *APERTURA)],
        Compradora(
            no_sabe_la_talla="no se mi talla",
            talla_de_lia=7,
            cantidad=["de dos huellitas"],
            colores=["una negra y la otra blanca toda"],
            grabado=["Toby y Nala"],
            nombre="Andrea Pérez",
            confirma="listo sí",
            paga_con="ya te transferí los 60 mil",
            total=250_000,
            en_el_resumen=("talla: 7", "toby"),
        ),
    ),
    Clienta(
        "valen_rafagas",
        "Valen",
        "570000000104",
        "escribe rápido, en ráfagas de mensajes cortos; paga con PDF",
        [
            P(
                "rafaga",
                rafaga=(
                    "Holaa",
                    "quiero un anillo de 3 huellitas",
                    "talla 7 y medio",
                    "todas rosadas",
                ),
                espera=(borrador(cantidad=3, talla=7.5, talla_lista=True),),
            ),
        ],
        Compradora(
            talla=["7 y medio"],
            cantidad=["3"],
            colores=["todas rosadas | las 3 igualitas"],
            grabado=["los nombres | Max, Coco y Bella"],
            nombre="Valentina Ríos",
            confirma="perfecto sii",
            paga_con="comprobante_pdf_60000",
            total=300_000,
            en_el_resumen=("3 huellitas", "talla: 7", "coco"),
        ),
        rafagas=True,
    ),
    Clienta(
        "dos_anillos",
        "Mónica",
        "570000000105",
        "dos anillos de tallas distintas en una sola compra",
        [P("apertura", "Hola! quiero dos anillos, uno para mí y otro para mi hermana")],
        Compradora(
            cantidad=["los dos de una huellita"],
            talla=["el mío talla 6 y el de ella talla 8"],
            misma_talla="no, el mío talla 6 y el de ella talla 8",
            colores=["el mío corazón rojo y deditos blancos", "el de ella todo celeste"],
            grabado=["el mío dice Rocky", "el de ella dice Kira"],
            nombre="Mónica Herrera",
            confirma="sí, así",
            paga_con="comprobante_120000",
            abono="120.000",
            total=400_000,
            en_el_resumen=("rocky", "kira", "talla: 6", "talla: 8"),
        ),
    ),
    Clienta(
        "cadena",
        "Sofía",
        "570000000106",
        "pregunta por la cadena y la compra",
        [
            P(
                "cadena",
                "Hola, ¿tienen cadenas?",
                dice("250.000", "65.000"),
                manda("cadena_1"),
                pidio_cadena=True,
            ),
            P("cadena", "sí, quiero una", pregunta(), pidio_cadena=True),
        ],
        Compradora(
            colores=["corazón azul zafiro y deditos blancos"],
            grabado=["Lado 1: Simba, lado 2: Te amo"],
            nombre="Sofía Martínez",
            confirma="así está bien",
            paga_con="comprobante_65000",
            abono="65.000",
            total=250_000,
            en_el_resumen=("cadena", "simba"),
        ),
        pidio_cadena=True,
    ),
    Clienta(
        "cambia_de_idea",
        "Camila",
        "570000000108",
        "cambia el color después del resumen",
        [P("apertura", "Hola, ¿qué precio tiene el de una huellita?", *APERTURA)],
        Compradora(
            talla=["talla 8"],
            cantidad=["una sola"],
            colores=["toda negra"],
            grabado=["Zeus"],
            nombre="Camila Torres",
            confirma="ahora sí, perfecto",
            cambio_tras_resumen="ay no, mejor el corazón morado y los deditos negros",
            en_el_resumen=("zeus",),
        ),
    ),
    Clienta(
        "mayusculas",
        "MARIA JOSE",
        "570000000111",
        "todo en mayúsculas, sin tildes, sin grabado",
        [P("apertura", "HOLA QUIERO EL DE 2 HUELLITAS!!!", *APERTURA)],
        Compradora(
            talla=["TALLA 5"],
            cantidad=["2"],
            colores=["LAS DOS NEGRAS"],
            grabado=["SIN NOMBRES"],
            nombre="MARIA JOSE CARDONA",
            confirma="SI ASI",
            total=250_000,
            en_el_resumen=("2 huellitas", "talla: 5"),
        ),
    ),
    Clienta(
        "ortografia",
        "Yeni",
        "570000000115",
        "escribe con muchos errores de ortografía y abreviaturas",
        [P("apertura", "ola bns tardes kiero info del anillo d huellitas", *APERTURA)],
        Compradora(
            talla=["mi talla es seis y medio"],
            cantidad=["d 2 guellitas"],
            colores=["la una roja tda y la otra con el corason azul y deditos blancos"],
            grabado=["q diga Kaiser y Mila"],
            nombre="yeni paola rojas",
            confirma="si asi esta bn",
            total=250_000,
            en_el_resumen=("2 huellitas", "talla: 6½", "kaiser"),
        ),
    ),
    Clienta(
        "pide_cuentas_antes",
        "Marcela",
        "570000000116",
        "pide a qué cuenta pagar antes de terminar de escoger",
        [
            P("apertura", "Hola", *APERTURA),
            P("talla", "talla 7", borrador(talla=7.0, talla_lista=True)),
            P(
                "cuentas antes",
                "¿a qué cuenta te consigno el abono?",
                dice("paula mantilla"),
                pregunta(),
                sin_pedido(),
                pidio_cuentas=True,
            ),
        ],
    ),
    Clienta(
        "yesi_insinua",
        "Yesi",
        "570000000121",
        "la conversación real del 05/10: sin anillos para medir, escoge todo menos la "
        "talla y su nombre y da a entender que quiere pagar ya («sí lo quiero, ¿cómo "
        "te pago?»): la cuenta sale, sin frenarla; paga y completa después",
        [
            P("apertura", "¡Hola! Quiero más información sobre el anillo", *APERTURA),
            P("talla", "Me regalas la guía", manda("medir_talla_guia")),
            P(
                "sin anillos",
                "No tengo anillos alguna otra manera ?",
                dice("tira de papel"),
                manda("medir_talla_dedo"),
            ),
            P(
                "colores",
                "Me gustaría solo 1 y que el centro sea verde esmeralda y arriba negro",
            ),
            P("grabado", "Will"),
            P("grabado", "Si por favor"),  # como en la charla real
            P(
                "cuenta insinuada",
                "Sí lo quiero, ¿cómo te pago?",
                # La talla la está midiendo en la joyería: no se le pide (09/10).
                dice("paula mantilla"),
                no_pide("talla"),
                no_dice("para poder iniciar", "primero"),
                sin_pedido(),
                pidio_cuentas=True,
            ),
            P(
                "comprobante",
                foto="comprobante_60000",
                espera=(no_dice("otro comprobante"), sin_pedido()),
            ),
            P("talla", "Ya fui a la joyería, me dijeron que soy talla 6"),
            P("nombre", "Yesica Duarte", pedido_en("EN_REVISION_PAGO")),
        ],
    ),
    Clienta(
        "ejemplos_y_foto",
        "Juliana",
        "570000000117",
        "pide ver anillos hechos y manda una foto de inspiración",
        [
            P(
                "apertura",
                "Hola, ¿tienes fotos de anillos que ya hayan hecho?",
                *APERTURA,
            ),
            P(
                "ejemplos",
                "me muestras más ejemplos porfa",
                manda(
                    "anillo_ejemplo",
                ),
            ),
            P(
                "foto de inspiracion",
                "quiero uno así",
                no_dice("recibido", "comprobante"),
                foto="anillo_que_vi",
            ),
        ],
    ),
    Clienta(
        "recoge",
        "Daniela",
        "570000000118",
        "es de Bucaramanga y quiere recoger el anillo",
        [
            P("apertura", "Hola! soy de Bucaramanga", *APERTURA),
            P(
                "recoger",
                "¿lo puedo recoger en vez de que me lo envíen?",
                dice("floridablanca", "recog", alguna=True),
            ),
        ],
    ),
    # -- con libreto -------------------------------------------------------------
    Clienta(
        "curiosa",
        "Diana",
        "570000000107",
        "pregunta, regatea y no compra",
        [
            P("apertura", "Buenas", *APERTURA),
            P("objeciones", "muy caro, ¿no tienen descuento?", no_dice("%"), pregunta()),
            P("objeciones", "¿hacen envíos a Pasto?", dice("envi", alguna=True)),
            P("objeciones", "¿y cuánto vale el envío?", dice("17.500")),
            P("objeciones", "¿es plata de verdad o se pela?", dice("925")),
            P("objeciones", "bueno lo pienso y te aviso", sin_pedido()),
        ],
    ),
    Clienta(
        "paga_antes",
        "Natalia",
        "570000000109",
        "manda el comprobante antes de terminar de escoger",
        [
            P("apertura", "Hola, ya conozco el anillo y quiero pedir uno", *APERTURA),
            P("talla", "talla 9", borrador(talla=9.0, talla_lista=True)),
            P("cantidad", "de una huellita", borrador(cantidad=1)),
            P(
                "comprobante",
                foto="comprobante_60000",
                espera=(no_dice("otro comprobante"), pregunta(), sin_pedido()),
            ),
            P("colores", "corazón verde esmeralda y deditos blancos"),
            P("grabado", "Pepa"),
            P("nombre", "Natalia Gil", pedido_en("EN_REVISION_PAGO")),
        ],
    ),
    Clienta(
        "medida_escrita",
        "Lucía",
        "570000000110",
        "escribe la medida del anillo en centímetros",
        [
            P("apertura", "hola", *APERTURA),
            P(
                "talla medida",
                "mi anillo mide 1.7 cm por dentro",
                dice("en unos minutos"),
                borrador(talla_en_revision=True),
                medida=True,
            ),
            P("cantidad", "una huellita", borrador(cantidad=1)),
        ],
    ),
    Clienta(
        "queja",
        "Carolina",
        "570000000112",
        "escribe con un reclamo de un anillo que ya compró",
        [
            P(
                "queja",
                "me llegó el anillo y se le cayó una piedrita, ¿qué hago?",
                no_manda("presentacion"),
                no_dice("$200.000"),
            ),
        ],
    ),
    Clienta(
        "vitrina",
        "Paola",
        "570000000113",
        "escribe desde la cadena de la vitrina del catálogo",
        [
            P(
                "vitrina",
                "Hola, ¿cuánto se demora?",
                dice("cadenita", "cadena", alguna=True),
                dice("250.000"),
                producto="CAD-HUE-1",
                pidio_cadena=True,
            ),
        ],
    ),
    Clienta(
        "vitrina_anillo",
        "Rocío",
        "570000000114",
        "escribe desde el anillo de 2 huellitas de la vitrina",
        [
            P("vitrina", "Hola, me interesa", *APERTURA, producto="ANI-HUE-2"),
            P("vitrina", "¿qué precio tiene?", dice("250.000")),
        ],
    ),
    Clienta(
        "nati_ubicacion",
        "Nati",
        "570000000125",
        "09/10: pregunta dónde están, mal escrito: Floridablanca, sin punto físico, "
        "solo el conjunto (nunca torre ni apartamento); y lo deja «pal otro mez»: "
        "con cariño, UNA vez, se le ofrece dejar el anillo listo (13/10); sin promesas",
        [
            P("apertura", "¿Qué precio tiene el anillo? 💍🐾", *APERTURA),
            P(
                "ubicacion",
                "y dnd qdan ubicados?",
                dice("floridablanca", "punto fisico", "caminos de provvidenza"),
                no_dice("torre", "apto", "301", "21-462"),
            ),
            P(
                "pospone",
                "ok gracias, pal otro mez lo hago",
                dice("dejemos tu anillo personalizado listo"),
                no_dice("te escribo", "recordatorio", "te recuerdo"),
            ),
        ],
    ),
    Clienta(
        "dani_cadena_dos",
        "Dani",
        "570000000126",
        "09/10: pide la cadena con dos huellitas: la información va de una y el "
        "sistema le dice que la cadena lleva una sola huellita",
        [
            P("apertura", "¿Qué precio tiene el anillo? 💍🐾", *APERTURA),
            P(
                "cadena",
                "la cadenita se puede con dos huellitas??",
                manda("cadena_1"),
                dice("una sola huellita"),
                pidio_cadena=True,
            ),
        ],
        pidio_cadena=True,
    ),
    Clienta(
        "lina_sin_grabado",
        "Lina",
        "570000000127",
        "09/10: rechaza una pregunta («no quiero grabado»): se acepta y no se le "
        "vuelve a preguntar; se sigue con lo que falta, una cosa a la vez",
        [
            P("apertura", "¿Qué precio tiene el anillo? 💍🐾", *APERTURA),
            P("talla", "soy talla 7", borrador(talla=7.0)),
            P("cantidad", "d una huellita", borrador(cantidad=1)),
            P("colores", "toda rosadita"),
            P(
                "grabado",
                "no quiero grabado, asi sencillo",
                no_dice("que nombre te gustaria grabar", "quieres grabar"),
            ),
        ],
    ),
    Clienta(
        "yulieth_dos_anillos",
        "Yulieth",
        "570000000128",
        "la charla real del 09/10: dos anillos, la medida «te las confirmo en la "
        "tarde»: no se le vuelve a pedir; lo que dijo para los dos (una huella cada "
        "uno, un color cada uno, Khalifa en los dos) no se le pregunta otra vez",
        [
            P("apertura", "¡Hola! Quiero más información", *APERTURA),
            P("guia", "Cómo te saco la medida para el anillo ?"),
            P(
                "dos anillos",
                "Osea que si mando a hacer dos anillos de diferentes medidas que valor "
                "tendría ?",
            ),
            P("cantidad", "Serían dos anillos cada anillo con una sola huella"),
            P(
                "la talla despues",
                "No la medida te las confirmo en la tarde pero sería uno más grande que "
                "el otro",
                no_pide("talla"),
            ),
            P("colores", "Una lila y la otra fucsia", no_pide("talla")),
            P(
                "grabado",
                "En los dos anillos Khalifa",
                no_pide("talla"),
                no_pide("colores"),
            ),
            P(
                "nombre",
                "De Yulieth Quijano",
                no_pide("talla"),
                no_pide("colores"),
                no_pide("grabado"),
                no_pide("cantidad de huellitas"),
            ),
            P("precio", "En cuanto salen los dos anillos ?", no_pide("talla")),
        ],
    ),
    Clienta(
        "no_le_gusta_la_plata",
        "Pilar",
        "570000000129",
        "la charla real del 08/10: pregunta por dorado y dice que no le gusta la "
        "plata: se cierra con cariño, sin ofrecerle la cadena (también es de "
        "plata), sin preguntas y sin recordatorios («te dije» no es «un dije»)",
        [
            P("apertura", "¿Qué precio tiene el anillo? 💍🐾", *APERTURA),
            P(
                "dorado",
                "5 y medio pero solo lo tienes en color plateado no tienes en dorado",
                dice("solo en plata"),
            ),
            P(
                "no le gusta",
                "Es que no me gusta la plata",
                no_pregunta(),
                no_manda("cadena_1"),
                borrador(sin_recordatorios=True),
            ),
            P(
                "insiste en que no",
                "No no los voy a pedir porque te dije que no me gusta la plata",
                no_pregunta(),
                no_manda("cadena_1"),
                no_dice("cadenita"),
                borrador(sin_recordatorios=True),
            ),
        ],
    ),
    # -- la auditoría del 13/10: charlas reales del 11 y el 12/10 -----------------
    Clienta(
        "por_separado",
        "Marcela",
        "570000000130",
        "pide ver los anillos «por separado» recién llegada la presentación: se le "
        "contesta lo que quiere (la foto es el de 3, los videos el de 1 y el de 2), "
        "sin devolverle «¿te refieres a…?» ni prometer fotos que no van",
        [
            P("apertura", "¡Hola! Quiero más información", *APERTURA),
            P(
                "por separado",
                "Me los puede mostrar por separado",
                # «la fotico es el de 3» o «el de 3 huellitas»: que diga cuál es cuál.
                dice("de 3", "3 huellitas", "tres huellitas", alguna=True),
                dice("de 2", "2 huellitas", "dos huellitas", alguna=True),
                no_dice("te refieres"),
            ),
        ],
    ),
    Clienta(
        "solo_gracias",
        "Sandra",
        "570000000131",
        "solo agradece la información: «¡Con gusto!» y ya, sin la pregunta de relleno",
        [
            P("apertura", "¡Hola! Quiero más información sobre los anillos", *APERTURA),
            P("gracias", "Gracias por la información", no_pregunta()),
        ],
    ),
    Clienta(
        "precio_otra_vez",
        "Gloria",
        "570000000132",
        "pregunta el precio justo después de la presentación (no la leyó): se le "
        "dan los precios, nunca «ya te los compartí»",
        [
            P("apertura", "¡Hola! Quiero más información", *APERTURA),
            P(
                "precio",
                "Hola me interesa su precios",
                dice("200.000"),
                no_dice("ya te compart"),
            ),
        ],
    ),
    Clienta(
        "solo_averiguando",
        "Patricia",
        "570000000133",
        "«Estaba averiguando solamente. Muchas gracias»: se despide con cariño, sin "
        "preguntarle nada",
        [
            P("apertura", "¡Hola! Quiero más información", *APERTURA),
            P(
                "se despide",
                "Estaba averiguando solamente \nMuchas gracias",
                no_pregunta(),
                borrador(sin_recordatorios=True),
            ),
        ],
    ),
    Clienta(
        "los_contacto",
        "Yesenia",
        "570000000134",
        "pide la guía y dice que cuando tenga la talla los contacta: con cariño y "
        "UNA vez se le ofrece dejar el anillo listo para que solo falten la talla y "
        "el abono; dice que sí y se sigue diseñando (Camilo, 13/10)",
        [
            P(
                "apertura",
                "Hola buenas tardes que precio tienen los anillos ?",
                *APERTURA,
            ),
            P("guia", "Me regalas la guía", manda("medir_talla")),
            P(
                "retoma despues",
                "Perfecto cuando tenga una talla los contactaré de nuevo gracias",
                dice("dejemos tu anillo personalizado listo", "la talla y el abono"),
            ),
            P("acepta", "Sí, de una", pregunta(), no_pide("talla")),
        ],
    ),
    Clienta(
        "nora_miedo_al_abono",
        "Nora",
        "570000000136",
        "la charla real del 13/10: le da miedo dar «plata adelantada». Se la "
        "tranquiliza desde el sentir (el abono hace SU anillo; el resto cuando lo "
        "vea terminado), con la página y el Instagram de verdad, sin apurarla con "
        "«¿De cuántas huellitas?»; y después sigue normal",
        [
            P("apertura", "¡Hola! Quiero más información", *APERTURA),
            P(
                "miedo",
                "Si pero no me gusta que tiene que dar vueltas lata adelantada",
                dice("lunajoyas.example", "lunajoyas"),
                dice("entiendo", "normal", alguna=True),
                no_pide("cantidad de huellitas"),
                no_dice("8 años", "mas de 8", "cientos"),
            ),
            P("sigue", "bueno listo, de una huellita", pregunta()),
        ],
    ),
    Clienta(
        "separa_sin_talla",
        "Daniela",
        "570000000137",
        "no tiene anillos para medirse: le llega cómo medirse el dedo. Cuando ya está "
        "todo menos la "
        "talla, se le ofrece UNA vez separarlo con el abono y mandar la talla después; "
        "dice que sí y le llegan el resumen y las cuentas (Camilo, 13/10)",
        [
            P("apertura", "¡Hola! Quiero más información", *APERTURA),
            P(
                "sin anillos",
                "no la sé y no tengo anillos para medirme",
                manda("medir_talla_dedo"),
            ),
            P("cantidad", "de una huellita"),
            P("colores", "toda rosada"),
            P("grabado", "que diga Max"),
            P(
                "nombre",
                "Daniela Pérez",
                # El ofrecimiento nombra la talla («me la mandas cuando la tengas»)
                # pero no se la pide: no va `no_pide("talla")`.
                dice("separar con el abono"),
                no_dice("guia", "joyeria"),
            ),
            P("separa", "sí, de una", dice("me la mandas después")),
            P("confirma", "sí, así está bien", dice("60.000")),
        ],
    ),
    Clienta(
        "ver_el_de_dos",
        "Liliana",
        "570000000135",
        "pide ver solo el de 2 huellitas: le llega ese video (el primero de la "
        "presentación), no los cinco mensajes otra vez",
        [
            P("apertura", "¡Hola! Quiero más información", *APERTURA),
            P(
                "ver uno",
                "me muestras como es el de 2 huellitas?",
                manda("presentacion_video_1"),
                no_manda("presentacion_video_2"),
                no_manda("presentacion_anillo"),
            ),
        ],
    ),
]
