"""«El flujo»: cómo vende el bot, con cada mensaje preestablecido tal cual sale.

Pedido de Camilo (29/09): que Lía vea TODO lo que está predefinido —la
apertura, la talla, los colores, el resumen, el abono, los avisos del taller,
los recordatorios— en el orden en que pasa, para que cuando quiera cambiar
algo diga exactamente qué («cambia el B2 por…»).

════════════════════════════════════════════════════════════════════════════
LOS TEXTOS NO SE COPIAN AQUÍ
════════════════════════════════════════════════════════════════════════════
Cada mensaje 🔒 fijo, 🧑‍🔧 del panel o 🕒 automático se lee de la MISMA
constante que usa el bot al mandarlo (`SALUDO_DE_APERTURA`, `AVISOS`,
`texto_del_recordatorio`…): si alguien cambia un texto, esta página cambia
sola. Los ✨ los redacta la IA: aquí va un ejemplo de su guía, y al final sus
instrucciones completas, leídas del mismo archivo que lee ella.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

#: Qué es cada mensaje, y cómo se pide un cambio.
TIPOS = {
    "fijo": ("🔒 Fijo", "Sale siempre igual. Se cambia el texto exacto."),
    "ia": ("✨ IA", "Lo redacta la IA siguiendo esta guía. Se cambia la guía."),
    "panel": ("🧑‍🔧 Panel", "Sale cuando tú tocas un botón en el panel."),
    "auto": ("🕒 Automático", "Sale solo, por tiempo."),
}


@dataclass
class Mensaje:
    codigo: str
    titulo: str
    tipo: str
    cuando: str
    texto: str = ""
    medios: list[tuple[str, str]] = field(default_factory=list)  # (tipo, nombre)
    nota: str = ""


@dataclass
class Etapa:
    letra: str
    titulo: str
    que_pasa: str
    mensajes: list[Mensaje]


def _hechos(c):
    """Los precios, el abono y los días: los mismos que tiene la asesora."""
    from app.conversacion.asesora import HechosDelNegocio

    hechos = getattr(c.bot, "_hechos", None)
    if hechos is not None:
        return hechos
    return HechosDelNegocio.del_catalogo(c.products.list_active())


def _ejemplo_de_borrador():
    """Una clienta de ejemplo para mostrar el resumen como le llega."""
    from app.domain.asesora import Borrador, HuellitaDelBorrador
    from app.domain.personalizacion import ColorCircon as C

    return Borrador(
        cantidad=2,
        talla=7.5,
        talla_confirmada=True,
        huellitas=[
            HuellitaDelBorrador(corazon=C.ROSADO, dedos=C.BLANCO),
            HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.NEGRO),
        ],
        grabado=["Luna", "Rocky"],
        nombre_clienta="Laura Gómez",
    )


def etapas(c) -> list[Etapa]:
    """El flujo entero, en orden, con los textos de verdad."""
    from app.conversacion import asesora as A
    from app.domain.asesora import SUGERENCIAS, pie_de_sugerencia
    from app.domain.faq import (
        PUNTO_DE_RECOGIDA,
        SOLO_EN_PLATA,
        UBICACION,
        datos_para_transferir,
    )
    from app.domain.guion import AVISOS, AVISOS_RECOGE, CUERPOS_META, aviso_de_cierre
    from app.domain.pricing import formatear_cop
    from app.domain.recordatorios import COLOMBIA
    from app.domain.recordatorios import texto as texto_del_recordatorio
    from app.domain.tallas import talla_texto
    from app.infra.container import Container

    h = _hechos(c)
    hoy = datetime.now(COLOMBIA).date()
    abono = formatear_cop(h.anticipo)
    ejemplo = _ejemplo_de_borrador()
    costo_envio = c.bot._mundo.envio_a(None) if hasattr(c.bot, "_mundo") else 17_500
    envio = formatear_cop(costo_envio)
    linea_envio = (
        f"Envíos nacionales tienen un valor de {envio} por COORDINADORA, ese valor lo "
        "puedes cancelar al recibir tu anillo 🚚❣️"
    )
    confirma_lia = c.settings.talla_la_confirma_lia
    # Pausados por Camilo (13/10): la tarjeta lo dice para que nadie los espere.
    pausa = (
        ""
        if c.settings.recordatorios
        else "⏸️ PAUSADO: hoy no sale ninguno (RECORDATORIOS=false). "
    )
    codigo = "PED-2026-0417"

    return [
        Etapa(
            "A",
            "El primer mensaje",
            "Escriba lo que escriba («hola», «precio», «vi tu anuncio»), le llega la "
            "presentación completa. No pasa por la IA: sale al instante y no cuesta "
            "nada. Si el primer mensaje es una queja o trae una foto, lo atiende la IA.",
            [
                Mensaje(
                    "A1",
                    "Saludo",
                    "fijo",
                    "Su primer mensaje. Según la hora de Colombia: este hasta las "
                    "12; de 12 a 7 p. m. «Buenas tardes 🌷» y de noche «Buenas "
                    "noches 🌙».",
                    A.SALUDO_DE_APERTURA,
                ),
                Mensaje(
                    "A2",
                    "Ficha del anillo (precios)",
                    "fijo",
                    "Justo después del saludo. Los precios, el abono y los días salen "
                    "de los productos del sistema.",
                    h.ficha(),
                ),
                Mensaje(
                    "A3",
                    "Los dos videos",
                    "fijo",
                    "Después de la ficha.",
                    medios=[
                        ("video", "presentacion_video_1"),
                        ("video", "presentacion_video_2"),
                    ],
                ),
                Mensaje(
                    "A4",
                    "Foto del anillo con la pregunta de la talla",
                    "fijo",
                    "Cierra la presentación: la pregunta va debajo de la foto.",
                    A.PREGUNTA_DE_LA_TALLA,
                    medios=[("imagen", "presentacion_anillo")],
                ),
                Mensaje(
                    "A5",
                    "¿Solo en plata? ¿No hay dorado?",
                    "fijo",
                    "Cuando pregunta si viene en dorado, en oro, con baño o en otro "
                    "metal (en cualquier momento). Es una regla: solo plata, porque los "
                    "baños se pelan. Debajo vuelve a la pregunta que estaba abierta. "
                    "«Corazón dorado» es otra cosa: es el circón amarillo.",
                    SOLO_EN_PLATA
                    + "\n\nY cuéntame, ¿"
                    + A.PREGUNTA_DE_LA_TALLA[1].lower()
                    + A.PREGUNTA_DE_LA_TALLA[2:],
                ),
                Mensaje(
                    "A6",
                    "¿Dónde están ubicados?",
                    "fijo",
                    "Cuando pregunta dónde están, si hay tienda o punto físico "
                    "(también mal escrito: «dnd qdan», «ubicasion»). Nunca la "
                    "dirección, la torre ni el apartamento: es la casa de Lía. Solo "
                    "el conjunto, para recoger sin costo. En Bucaramanga, domicilio "
                    "sin cifra. Debajo vuelve a la pregunta que estaba abierta.",
                    UBICACION
                    + "\n\nY cuéntame, ¿"
                    + A.PREGUNTA_DE_LA_TALLA[1].lower()
                    + A.PREGUNTA_DE_LA_TALLA[2:],
                ),
                Mensaje(
                    "A7",
                    "La cadena (solo si ella pregunta)",
                    "fijo",
                    "NUNCA se ofrece. Si pregunta por cadenas, collares o más "
                    "productos, la información va de una, con 3 fotos. Lleva UNA "
                    "huellita, siempre: si la pide con más, primero le llega «La "
                    "cadenita se hace con una sola huellita 🐾…».",
                    A.MENSAJE_DE_LA_CADENA.format(
                        precio=formatear_cop(getattr(h, "precio_cadena", 250_000)),
                        abono=formatear_cop(getattr(h, "anticipo_cadena", 65_000)),
                    )
                    + "\n\n"
                    + A.PREGUNTA_DE_LA_CADENA,
                    medios=[("imagen", f) for f in A.FOTOS_DE_LA_CADENA],
                ),
                Mensaje(
                    "A8",
                    "El anillo de corazón (sí se ofrece)",
                    "fijo",
                    "El otro diseño (17/10): un corazón de circón del color que ella "
                    "escoja, en vez de huellitas; lo demás igual que el de huellita "
                    "(talla, hasta 5 nombres por dentro, abono, tiempos). A diferencia "
                    "de la cadena, se puede ofrecer desde el primer mensaje: si "
                    "pregunta por él, por uno «sin huella» o «solo con la piedrita», "
                    "o si es para su pareja o una promesa.",
                    h.ficha_del_corazon() + "\n\n" + A.PREGUNTA_DEL_CORAZON,
                    medios=[("imagen", f) for f in A.FOTOS_DEL_CORAZON],
                ),
            ],
        ),
        Etapa(
            "B",
            "La talla",
            (
                "Regla de Lía: la talla la confirma Lía, siempre, antes del abono. "
                "El bot mira la foto de la regla pero no le dice ninguna talla; le "
                "dice que en unos minutos se la confirman y sigue con los colores. "
                "La foto aparece en el panel en «📏 Tallas por confirmar» y te llega "
                "un aviso al celular."
                if confirma_lia
                else "La IA calcula la talla de la foto o la medida y se la dice como "
                "referencia; Lía la revisa en el panel."
            ),
            [
                Mensaje(
                    "B1",
                    "La guía para medir",
                    "fijo",
                    "Cuando dice que no sabe su talla o pide la guía.",
                    "¡Dale! Te la comparto 📏\n\n" + A.GUIA_TALLA,
                    medios=[("imagen", "medir_talla_guia")],
                ),
                Mensaje(
                    "B2",
                    "Recibí tu medida",
                    "fijo",
                    "Cuando manda la foto de la regla o escribe la medida.",
                    A.TALLA_EN_REVISION,
                ),
                Mensaje(
                    "B3",
                    "Tu talla confirmada",
                    "panel",
                    "Cuando Lía confirma la talla en el panel. Si Lía escribe su propio "
                    "mensaje, sale el de ella en vez de este. Si ya había escogido todo, "
                    "detrás le llega el resumen (E1).",
                    A.TALLA_CONFIRMADA.format(talla=talla_texto(7.5)),
                ),
                Mensaje(
                    "B4",
                    "Ya casi, solo falta la talla",
                    "fijo",
                    "Cuando ya escogió todo y solo falta que Lía confirme la talla.",
                    A.TALLA_EN_ESPERA,
                ),
                Mensaje(
                    "B5",
                    "No tiene anillos para medir",
                    "fijo",
                    "Cuando dice que no tiene anillos («no tengo anillos», «no uso»): "
                    "el contorno del dedo con papel o hilo y el video de cómo se hace "
                    "(Camilo, 13/10; antes, la joyería). Ella manda los centímetros y "
                    "Lía confirma la talla. Si todavía falta escoger algo, el bot sigue "
                    "armando el anillo mientras tanto.",
                    A.TALLA_SIN_ANILLOS
                    + "\n[video: cómo medirse el dedo] "
                    + A.PIE_DEL_VIDEO_DEL_DEDO
                    + "\n\n"
                    + A.MIENTRAS_TANTO
                    + " "
                    + A.COMO_SE_PREGUNTA["cantidad de huellitas"],
                ),
            ],
        ),
        Etapa(
            "C",
            "Cantidad, colores y diseño",
            "Mientras Lía revisa la talla, el bot sigue: cuántas huellitas, de qué "
            "colores el corazón y los deditos de cada una. Apenas quedan los colores, "
            "le llega sola la foto de cómo le queda.",
            [
                Mensaje(
                    "C1",
                    "¿Cuántas huellitas?",
                    "ia",
                    "Después de la talla. Si su respuesta no es clara, se le pregunta "
                    "con opciones (hasta 3 veces; después se le pasa a Lía).",
                    A.COMO_SE_PREGUNTA["cantidad de huellitas"]
                    + "\n\n"
                    + "\n".join(A.PREGUNTAS_DE_CANTIDAD),
                ),
                Mensaje(
                    "C2",
                    "El muestrario de colores",
                    "fijo",
                    "La primera vez que se habla de colores.",
                    "Estos son los colores de circón que manejamos 🩵🩷",
                    medios=[("imagen", "muestrario_circones")],
                ),
                Mensaje(
                    "C3",
                    "Así se te va a ver",
                    "fijo",
                    "Apenas escoge los colores: el sistema dibuja SU anillo con SUS "
                    "colores. Si pide ver otro color sin escogerlo, se dibuja ese.",
                    "Así se te va a ver 😍💍",
                    nota="La foto se genera con sus colores; no es una foto fija.",
                ),
                Mensaje(
                    "C4",
                    "Sugerencias de diseño",
                    "fijo",
                    "Solo si pide consejo («¿cuál me recomiendas?»): 4 diseños.",
                    " · ".join(pie_de_sugerencia(c) for c in SUGERENCIAS),
                ),
                Mensaje(
                    "C5",
                    "Anillos de ejemplo",
                    "fijo",
                    "Si pide ver anillos hechos.",
                    medios=[
                        ("imagen", "anillos_inspirado_en_tu_mascota"),
                        ("imagen", "anillo_ejemplo_1"),
                        ("imagen", "muestrario_circones"),
                    ],
                ),
                Mensaje(
                    "C6",
                    "La forma del anillo no se cambia",
                    "ia",
                    "Si pide otra dirección u orden de las huellitas: se le explica con "
                    "cariño que así es el diseño. Lo que sí escoge son los colores.",
                ),
            ],
        ),
        Etapa(
            "D",
            "Grabado y nombre",
            "Lo último antes del resumen. Los datos de envío (ciudad, cédula, "
            "dirección) NO se piden aquí: van al final, con las fotos del anillo.",
            [
                Mensaje(
                    "D1",
                    "El grabado",
                    "ia",
                    "Después de los colores. Hasta 5 nombres; también puede ir liso.",
                    "¿Y con cuál grabado en el aro? Nombre(s), iniciales 🐶🐱 Puedes "
                    "grabar hasta 5 nombres",
                ),
                Mensaje(
                    "D2",
                    "Su nombre",
                    "ia",
                    "Después del grabado. Si en WhatsApp tiene nombre, se le propone.",
                    "¿A nombre de quién va el pedido? 🥰\n\n"
                    "(o, si se sabe: ¿Lo dejo a nombre de Laura Gómez? 🥰)",
                ),
            ],
        ),
        Etapa(
            "E",
            "Resumen y abono",
            "Con todo escogido (y la talla confirmada por Lía) le llega el resumen. "
            "Cuando dice que sí, nace el pedido y le llegan las cuentas del abono.",
            [
                Mensaje(
                    "E1",
                    "El resumen",
                    "fijo",
                    "Apenas está todo. Ejemplo con una clienta inventada:",
                    ejemplo.resumen() + "\n\n" + A.CONFIRMA_EL_RESUMEN,
                ),
                Mensaje(
                    "E2",
                    "Las cuentas del abono",
                    "fijo",
                    "Cuando confirma el resumen («sí», «listo»). Aquí nace el pedido "
                    "y aparece en el panel. También ANTES, si ella pide la cuenta o da "
                    "a entender que quiere pagar («¿cómo te pago?», «regálame la "
                    "cuenta»), aunque falten datos: se le manda y debajo se le pide "
                    "con cariño lo que falta («Cuando puedas, ¿me compartes tu talla y "
                    "tu nombre completo…?»); el pedido nace cuando esté completo. Si "
                    "ella no habla de pagar, el bot no la apura con el pago.",
                    "\n".join(
                        [
                            f"*A esta cuenta puedes transferir los {abono} del abono "
                            "del anillo 💓*",
                            "",
                            datos_para_transferir(),
                            "",
                            linea_envio,
                        ]
                    ),
                    nota="Si es de Bucaramanga o cerca, se le ofrece recogerlo en "
                    f"{PUNTO_DE_RECOGIDA}.",
                ),
                Mensaje(
                    "E3",
                    "Quedo atenta",
                    "fijo",
                    "Una sola vez, debajo de las cuentas. Mientras ella va a pagar, "
                    "no se le pregunta nada más (si dice «gracias» o «mañana te "
                    "consigno», se le agradece y ya).",
                    A.QUEDO_ATENTA,
                ),
                Mensaje(
                    "E4",
                    "¡Recibido!",
                    "ia",
                    "Cuando manda el comprobante. Nunca dice que el pago está "
                    "confirmado: eso lo verifica Lía en el banco.",
                    "¡Recibido! 🙌\n\nPerfecto Laura 🫶 Ya tomé tu pedido. Tan pronto "
                    "esté listo (10-15 días o antes), te comparto las fotos de cómo "
                    "quedó 🙌💓 ¡Mil gracias por tu confianza! ❣️",
                ),
                Mensaje(
                    "E5",
                    "Recordatorio (el primero)",
                    "auto",
                    pausa + "Si se queda callada ANTES del abono y escribió "
                    "al menos dos "
                    "mensajes: uno útil según en qué se quedó (talla, guía, "
                    "colores, grabado, nombre, resumen o abono). SOLO a las 9 a. m. o "
                    "a las 5 p. m.: si escribió antes de las 9 a. m., a las 5 p. m. "
                    "de ese día; si escribió después, a las 9 a. m. del día "
                    "siguiente (siempre dentro de sus 24 h). Este es el de la talla "
                    "con la guía; cada etapa tiene el suyo.",
                    texto_del_recordatorio(
                        1, "talla_guia", nombre="Laura", pieza="anillo", hoy=hoy
                    ),
                ),
                Mensaje(
                    "E6",
                    "Recordatorio (el último)",
                    "auto",
                    pausa + "Solo si cabe otro horario antes de que se "
                    "cierren sus 24 h (en "
                    "la práctica, a quien escribió de noche: a las 9 a. m. y a las "
                    "5 p. m.). Le da una razón para hacerlo hoy. Si dijo «lo pienso» "
                    "o «te aviso», es el único de la ventana.",
                    texto_del_recordatorio(
                        2, "abono", nombre="Laura", pieza="anillo", hoy=hoy
                    ),
                ),
                Mensaje(
                    "E7",
                    "Recordatorio con plantilla (a los 3 días)",
                    "auto",
                    pausa + "Solo si ya había invertido en su diseño "
                    "(guía de talla, colores, "
                    "grabado, nombre, resumen o abono) y sigue callada: a los 3 días, "
                    "en el horario más cercano a cuando ella escribe (9 a. m. o "
                    "5 p. m.). Es una "
                    "plantilla de Meta (~US$0,0125) con dos botones: «Sí, sigamos» y "
                    "«Más adelante». Una vez por semana como mucho. Después de esto, "
                    "nada más hasta que ella escriba.",
                    texto_del_recordatorio(
                        3, "colores", nombre="Laura", pieza="anillo", hoy=hoy
                    ),
                ),
                Mensaje(
                    "E8",
                    "Recordatorio de lo que dijo que manda después",
                    "auto",
                    pausa + "Si dijo que algo lo manda después "
                    "(«la medida te la confirmo en "
                    "la tarde»), en la charla no se le vuelve a pedir, y le llega "
                    "SOLO este recordatorio, sobre eso mismo, en su horario. Ni el "
                    "segundo ni la plantilla. Hay uno para la talla, la cantidad, los "
                    "colores, el grabado y su nombre; este es el de la talla.",
                    texto_del_recordatorio(
                        1, "despues_talla", nombre="Yulieth", pieza="pedido", hoy=hoy
                    ),
                ),
            ],
        ),
        Etapa(
            "F",
            "El taller (los botones del panel)",
            "Desde aquí mueve Lía el pedido. Los botones con ✉ le escriben a la "
            "clienta; en todos puedes agregar un mensaje tuyo y una nota interna. Lo "
            "que falte de un pedido se escribe en «✏️ Datos del pedido».",
            [
                Mensaje(
                    "F1",
                    "Abono recibido",
                    "panel",
                    "El pedido sale en «💰 Pagos por verificar» cuando manda el "
                    "comprobante. Lo ves en el banco y tocas el botón. No le escribe "
                    "nada: queda «Listos para fabricar».",
                ),
                Mensaje(
                    "F2",
                    "✉ Empezar a fabricar",
                    "panel",
                    "Entra al taller. Solo deja si el pedido está completo (ver «Lo "
                    "obligatorio» arriba).",
                    AVISOS["EN_PRODUCCION"].format(codigo=codigo),
                ),
                Mensaje(
                    "F3",
                    "✉ Cobrar el saldo",
                    "panel",
                    "El anillo quedó y ya subiste las fotos (sin fotos no deja). Van: "
                    "este mensaje, las fotos y el cobro. Aquí se le piden los datos de "
                    "envío: cuando los manda, el bot los lee y los guarda solo.",
                    AVISOS["ESPERANDO_SALDO"].format(
                        envio_del_mensaje=envio, codigo=codigo
                    )
                    + "\n\n📷 (las fotos del anillo)\n\n"
                    + aviso_de_cierre(
                        recoge=False, saldo_cop=140_000, envio_cop=costo_envio
                    ),
                ),
                Mensaje(
                    "F4",
                    "✉ Cobrar el saldo · si lo recoge",
                    "panel",
                    "Lo mismo, para quien lo pasa a recoger: sin envío ni datos de guía.",
                    AVISOS_RECOGE["ESPERANDO_SALDO"]
                    + "\n\n📷 (las fotos del anillo)\n\n"
                    + aviso_de_cierre(recoge=True, saldo_cop=140_000),
                ),
                Mensaje(
                    "F5",
                    "Si le falta algún dato de envío",
                    "ia",
                    "Si mandó los datos incompletos, el bot le pide lo que falta, de a "
                    "uno. Si ella no lo sabe escribir bien, lo pones tú en «✏️ Datos "
                    "del pedido».",
                    "\n".join(
                        A.COMO_SE_PREGUNTA[q]
                        for q in (
                            "ciudad",
                            "cédula",
                            "celular",
                            "dirección completa con barrio y nomenclatura",
                        )
                    ),
                ),
                Mensaje(
                    "F6",
                    "Saldo recibido",
                    "panel",
                    "Sale en «💰 Pagos por verificar» (dice SALDO). Lo ves en el "
                    "banco y confirmas. No le escribe: queda «Por despachar».",
                ),
                Mensaje(
                    "F7",
                    "✉ Despachado (con la guía)",
                    "panel",
                    "Lo llevaste a la transportadora. En el recuadro 🚚 junto al botón "
                    "escribes la transportadora (viene Coordinadora) y el número de "
                    "guía: sin guía NO se despacha. La guía le llega en el mensaje.",
                    AVISOS["DESPACHADO"].format(
                        codigo=codigo,
                        envio_contraentrega=envio or "el envío",
                        transportadora="Coordinadora",
                        guia="700012345678",
                    ),
                ),
                Mensaje(
                    "F8",
                    "✉ Listo para recoger (si lo recoge)",
                    "panel",
                    "Para quien lo recoge, «Despachado» es «ya te está esperando». No "
                    "necesita guía.",
                    AVISOS_RECOGE["DESPACHADO"].format(
                        codigo=codigo, punto_de_recogida=PUNTO_DE_RECOGIDA
                    ),
                ),
                Mensaje(
                    "F9",
                    "Si pasaron más de 24 horas",
                    "auto",
                    "WhatsApp solo deja escribirle libre dentro de las 24 h de su último "
                    "mensaje. Fuera de eso sale la plantilla aprobada por Meta (la del "
                    "despacho no lleva la guía: se la mandas cuando ella conteste):",
                    "\n\n— — —\n\n".join(CUERPOS_META.values()),
                ),
            ],
        ),
        Etapa(
            "G",
            "Casos especiales",
            "Lo que pasa cuando algo sale del camino normal.",
            [
                Mensaje(
                    "G1",
                    "La IA no contesta",
                    "fijo",
                    "Si Claude se cae o se queda sin saldo: le dice esto, la "
                    "conversación pasa a Lía en Chatwoot y te llega un aviso al celular.",
                    "¡Hola! 💓 Dame un momentico y ya te atiendo 🙌",
                ),
                Mensaje(
                    "G2",
                    "Algo falló en el sistema",
                    "fijo",
                    "Si un turno se cae entero. También pasa a Lía.",
                    Container.AUXILIO,
                ),
                Mensaje(
                    "G3",
                    "Queja o reclamo",
                    "ia",
                    "La IA la escucha con calma, no le manda precios y se la pasa a Lía "
                    "(etiqueta «necesita-persona» en Chatwoot).",
                ),
                Mensaje(
                    "G4",
                    "Cuando tú contestas",
                    "panel",
                    "Quien está asignado es quien atiende. Si le escribes desde el "
                    "panel o Chatwoot, o te la asignas, queda asignada a ti y el bot "
                    "se calla en ESA conversación. Vuelve cuando te la quitas "
                    "(«Agente asignado» → «Ninguna»), con «Que siga el bot» o la "
                    "macro «🤖 Devolver al bot», o si pasan 12 h sin que escribas. "
                    "«Resolver» solo cierra: no la devuelve.",
                ),
                Mensaje(
                    "G5",
                    "Algo que WhatsApp no deja ver",
                    "ia",
                    "Una foto «de una sola vista», una encuesta: el bot no la puede ver "
                    "y le pide con cariño que la mande normal.",
                ),
            ],
        ),
    ]


#: (qué pasa, qué hace el bot, qué haces tú). Los caminos que no son el normal.
CAMINOS: tuple[tuple[str, str, str], ...] = (
    (
        "Paga antes de terminar de escoger",
        "Le recibe el comprobante (queda «pagó sin pedido») y le sigue preguntando lo "
        "que falta. El pedido nace solo cuando está todo, y ahí queda «por verificar».",
        "Nada distinto: verificas el abono cuando aparezca en «💰 Pagos por verificar».",
    ),
    (
        "Termina todo y la talla no está confirmada",
        "No le pide el abono. Le dice que ya casi, que en unos minutos le confirmas la "
        "talla (B4), y te llega un aviso al celular.",
        "Confirmas la talla en «📏 Tallas por confirmar»: le llega su talla y el "
        "resumen, y sigue sola al abono.",
    ),
    (
        "Lo quiere recoger (en el conjunto, no hay tienda)",
        "No le pide dirección ni cédula; en las cuentas le ofrece recogerlo si es de "
        "Bucaramanga o cerca.",
        "Al terminar: «Cobrar el saldo» y luego «Despachado» (le dice que ya la está "
        "esperando). No hace falta guía.",
    ),
    (
        "Quiere pagar el envío por adelantado",
        "Se le cobra JUNTO con el saldo (nunca con el abono) y al despacharlo se le "
        "dice que no paga nada al recibir.",
        "Nada distinto.",
    ),
    (
        "Pide otra transportadora (Interrapidísimo, Servientrega…)",
        "Le dice que eso lo arreglas tú y te pasa la conversación (queda en «🙋 Me "
        "necesitan» en Chatwoot).",
        "Si aceptas, al despachar cambias la transportadora en el recuadro 🚚.",
    ),
    (
        "Lo deja para después («el otro mes», «pal mes q viene», «mañana»)",
        "Le agradece y cierra, sin preguntas y sin prometerle escribir. Si es para "
        "otro mes, no le manda recordatorios. Si ELLA pide que le escriban, le dice "
        "que sí (sin fecha) y te deja una nota «📅» en Chatwoot.",
        "Si te dejó la nota «📅», le escribes tú cuando toque.",
    ),
    (
        "Contesta solo una parte, o no quiere contestar algo",
        "A medias: anota y le pregunta lo siguiente que falta, UNA cosa a la vez; lo "
        "que no contestó se lo pide UNA vez más y después lo deja al recordatorio. "
        "Si rechaza algo opcional («no quiero grabado»), lo acepta y no vuelve a "
        "preguntarlo; si es indispensable (talla, colores), le explica por qué en "
        "una frase y sigue. Lo que dijo para todos los anillos («cada uno con una "
        "huella», «Khalifa en los dos») queda en cada uno.",
        "Nada.",
    ),
    (
        "No le interesa, por poco que sea («no me gusta la plata», «muy caro», "
        "«solo miraba»)",
        "Le agradece y cierra en una frase, sin ofrecerle nada ni preguntarle. Ningún "
        "recordatorio más: antes de cada uno la IA lee la charla y, si ve desinterés, "
        "no sale (aunque esté mal escrito).",
        "Nada.",
    ),
    (
        "Dice que algo lo manda después («la medida te la confirmo en la tarde»)",
        "No se lo vuelve a pedir en la charla (ni con pregunta ni con «mándame»). "
        "Sigue con lo demás y le llega UN recordatorio sobre eso (E8), y ya.",
        "Nada, salvo que quieras escribirle tú.",
    ),
    (
        "Cambia un dato después de pagar",
        "Talla, colores o grabado: si el anillo aún no entra al taller, se cambia y te "
        "deja una nota; si ya está en el taller, te lo pasa a ti. Datos de envío: se "
        "cambian solos hasta que se despacha.",
        "Revisas la nota antes de fabricar, o lo corriges en «✏️ Datos del pedido».",
    ),
    (
        "La dirección o un dato no le queda bien al bot",
        "Le vuelve a preguntar lo que no entendió.",
        "Lo escribes tú en «✏️ Datos del pedido» (o en la ficha de Chatwoot): queda en "
        "el pedido, en el bot y en Chatwoot.",
    ),
    (
        "Se queda callada antes del abono (talla, colores, resumen, abono…)",
        "Si escribió al menos dos mensajes: uno según en qué se quedó, otro si cabe "
        "antes de que se cierren sus 24 h y, si ya había avanzado en su diseño, uno a "
        "los 3 días (E5, E6, E7). Solo a las 9 a. m. o a las 5 p. m. Si dice que no, "
        "nunca más.",
        "Nada, salvo que quieras escribirle tú.",
    ),
    (
        "Se cancela o hay que devolver la plata",
        "No le escribe nada.",
        "En el taller: «Cancelar» o «Reembolsar» (no se deshace; te pregunta antes).",
    ),
)

#: Lo que tiene que estar para poder dar cada paso. Es lo que revisa el sistema.
OBLIGATORIO: tuple[tuple[str, str, str], ...] = (
    (
        "Para pedirle el abono",
        "Cantidad de huellitas · talla CONFIRMADA por Lía · colores de cada huellita "
        "· grabado (o «sin grabado») · su nombre",
        "El bot no le manda las cuentas del abono hasta que esté todo.",
    ),
    (
        "Para entrar al taller",
        "Todo lo anterior y el abono confirmado",
        "El botón «Empezar a fabricar» dice qué falta.",
    ),
    (
        "Para cobrar el saldo",
        "Las fotos del anillo terminado",
        "Sin fotos no deja: el cobro se las manda a ella.",
    ),
    (
        "Para despachar",
        "Ciudad · a nombre de quién · cédula · celular · dirección completa · número "
        "de guía (o que lo recoge)",
        "Lo que falte se escribe en «✏️ Datos del pedido»; la guía, junto al botón.",
    ),
)


def _pesos_envio() -> str:
    from app.domain.faq import ENVIO_EN_EL_MENSAJE_COP
    from app.domain.pricing import formatear_cop

    return formatear_cop(ENVIO_EN_EL_MENSAJE_COP)


# ══════════════════════════════════════════════════════════════════════════
#  La página
# ══════════════════════════════════════════════════════════════════════════

ESTILO_FLUJO = """
.leyenda{display:grid;gap:6px;margin:10px 0 4px}
.leyenda div{font-size:13px;color:var(--suave)}
.tipo{display:inline-block;font-size:12px;font-weight:600;border-radius:999px;
padding:1px 9px;margin-right:6px;white-space:nowrap}
.tipo.fijo{background:#eef3ff;color:#2d4a8a}
.tipo.ia{background:#f6ecff;color:#6a3a93}
.tipo.panel{background:#fff3e6;color:#8a4f12}
.tipo.auto{background:#eaf6ee;color:#2f6b45}
.ruta-flujo{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}
.ruta-flujo a{font-size:13px;text-decoration:none;color:var(--texto);
background:var(--tarjeta);border:1px solid var(--borde);border-radius:999px;
padding:4px 11px}
.ruta-flujo a:hover{border-color:var(--acento)}
.cod{font-family:ui-monospace,Consolas,monospace;font-weight:700;
background:var(--acento);color:#fff;border-radius:6px;padding:1px 7px;
margin-right:6px;font-size:13px}
.cuando{color:var(--suave);font-size:13px;margin:4px 0 8px}
.burbuja.mio{max-width:100%;white-space:normal}
.medios{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}
.medios img,.medios video{width:120px;height:120px;object-fit:cover;
border-radius:9px;border:1px solid var(--borde);background:#f2ecea}
.nota-flujo{font-size:12px;color:var(--suave);margin-top:6px}
details.prompt pre{white-space:pre-wrap;font-size:12px;line-height:1.5;
background:#f4f1f0;border:1px solid var(--borde);border-radius:9px;padding:10px;
max-height:520px;overflow:auto}
"""


def pagina(c, token: str, cabecera) -> str:
    """La página entera. `cabecera` es la del panel (mismo estilo y la llave)."""
    tok = html.escape(token)
    cuerpo = [
        cabecera("El flujo · Luna Joyas").replace(
            "</style>", ESTILO_FLUJO + "</style>"
        ),
        "<header><h1>Cómo vende el bot</h1><div class=sub>"
        f"<a href='/panel?token={tok}'>← taller</a> · "
        f"<a href='/panel/chats?token={tok}'>conversaciones</a> · "
        f"<a href='/panel/instructivo?token={tok}'>📖 instructivo</a></div></header>"
        "<main>",
        "<section><p>Esto es, en orden, lo que le llega a una clienta desde que "
        "escribe hasta que recibe su anillo. <b>Los textos son los de verdad</b>: "
        "si se cambia uno, aquí se ve el nuevo.</p>"
        "<p class=ayuda>Para pedir un cambio, di el <b>código</b> y cómo lo "
        "quieres. Por ejemplo: «En el B2 quiero que diga…» o «El E5 que salga a "
        "las 48 horas».</p><div class=leyenda>",
    ]
    for clave, (nombre, que) in TIPOS.items():
        cuerpo.append(f"<div><span class='tipo {clave}'>{nombre}</span>{que}</div>")
    cuerpo.append("</div></section>")

    cuerpo.append(_lo_obligatorio(c, tok))
    todas = etapas(c)
    cuerpo.append("<nav class=ruta-flujo>")
    cuerpo.append("<a href='#obligatorio'>Lo obligatorio</a>")
    for i, e in enumerate(todas):
        flecha = " →" if i < len(todas) - 1 else ""
        cuerpo.append(
            f"<a href='#etapa-{e.letra}'>{e.letra} · {html.escape(e.titulo)}{flecha}</a>"
        )
    cuerpo.append("<a href='#caminos'>Otros caminos</a>")
    cuerpo.append("<a href='#la-ia'>Lo que sabe la IA</a>")
    cuerpo.append("</nav>")

    for e in todas:
        cuerpo.append(
            f"<section id='etapa-{e.letra}'><h2>{e.letra} · {html.escape(e.titulo)}</h2>"
            f"<p class=ayuda>{html.escape(e.que_pasa)}</p>"
        )
        for m in e.mensajes:
            cuerpo.append(_tarjeta(m))
        cuerpo.append("</section>")

    cuerpo.append(_los_caminos())
    cuerpo.append(_lo_que_sabe_la_ia(c))
    cuerpo.append("</main></body></html>")
    return "".join(cuerpo)


def _lo_obligatorio(c, tok: str) -> str:
    from app.domain.pricing import formatear_cop

    envio = c.bot._mundo.envio_a(None) if hasattr(c.bot, "_mundo") else 17_500
    filas = "".join(
        f"<article><b>{html.escape(paso)}</b><div class=dato>{html.escape(que)}</div>"
        f"<div class=cuando>{html.escape(como)}</div></article>"
        for paso, que, como in OBLIGATORIO
    )
    return (
        "<section id=obligatorio><h2>Lo obligatorio en cada paso</h2>"
        "<p class=ayuda>El sistema no deja avanzar sin esto. Todo se puede escribir "
        "a mano en el taller («✏️ Datos del pedido»).</p>"
        f"{filas}"
        f"<p class=ayuda>Envío: <b>{formatear_cop(envio)}</b> a todo el país "
        f"(<a href='/panel/envios?token={tok}'>cambiarlo en Envíos</a>).</p>"
        "</section>"
    )


def _los_caminos() -> str:
    tarjetas = "".join(
        f"<article><b>{html.escape(que)}</b>"
        f"<div class=dato>🤖 {html.escape(bot)}</div>"
        f"<div class=cuando>🧑‍🔧 Tú: {html.escape(tu)}</div></article>"
        for que, bot, tu in CAMINOS
    )
    return (
        "<section id=caminos><h2>Caminos que no son el normal</h2>"
        "<p class=ayuda>Qué hace el bot y qué te toca a ti en cada caso.</p>"
        f"{tarjetas}</section>"
    )


def _tarjeta(m: Mensaje) -> str:
    nombre, _ = TIPOS[m.tipo]
    partes = [
        f"<article id='{m.codigo}'>",
        f"<div><span class=cod>{m.codigo}</span><b>{html.escape(m.titulo)}</b> "
        f"<span class='tipo {m.tipo}'>{nombre}</span></div>",
        f"<div class=cuando>{html.escape(m.cuando)}</div>",
    ]
    if m.medios:
        partes.append("<div class=medios>")
        for tipo, archivo in m.medios:
            url = f"/media/{html.escape(archivo)}"
            if tipo == "video":
                partes.append(f"<video src='{url}' controls preload=metadata></video>")
            else:
                partes.append(f"<img src='{url}' alt='' loading=lazy>")
        partes.append("</div>")
    if m.texto:
        texto = html.escape(m.texto).replace("\n", "<br>")
        partes.append(f"<div class=chat><div class='burbuja mio'>{texto}</div></div>")
    if m.nota:
        partes.append(f"<div class=nota-flujo>{html.escape(m.nota)}</div>")
    partes.append("</article>")
    return "".join(partes)


def _lo_que_sabe_la_ia(c) -> str:
    """Los hechos del negocio y las reglas completas, plegados."""
    hechos = _hechos(c)
    ruta = Path(__file__).resolve().parents[1] / "prompts" / "asesora_v1.txt"
    try:
        reglas = ruta.read_text(encoding="utf-8").replace(
            "{hechos}", hechos.para_el_prompt()
        )
    except OSError:
        reglas = "(no se pudieron leer las instrucciones)"
    return (
        "<section id='la-ia'><h2>Lo que sabe la IA</h2>"
        "<p class=ayuda>Los mensajes ✨ los escribe la IA con estas instrucciones. "
        "Aquí están completas, por si quieres ver exactamente qué se le dice.</p>"
        "<details class=prompt><summary>Los datos del negocio que conoce</summary>"
        f"<pre>{html.escape(hechos.para_el_prompt())}</pre></details>"
        "<details class=prompt><summary>Sus instrucciones completas</summary>"
        f"<pre>{html.escape(reglas)}</pre></details></section>"
    )
