"""La hoja CENTRO DE MANDO del ERP: dónde está todo, escrito por el propio bot.

Camilo, 20/09: «si lo pongo en un servidor no sé dónde voy a ver ese link…
tal vez una hoja más del ERP, algo fácil y supremamente estándar para siempre
saber dónde buscar el panel total».

El problema de fondo es que la dirección del bot NO es fija: cambia con el
túnel, con la máquina, con el servidor. Lo único que sí es fijo es el ERP —
es la misma hoja de Google siempre, se abre desde cualquier teléfono, y Camilo
ya sabe dónde está—. Así que el bot escribe ahí su propia dirección cada vez
que arranca, y la vuelve a escribir cada 10 minutos. Esté donde esté, la hoja
dice dónde.

La hora de «visto vivo» se reescribe en cada vuelta, así que también responde
la otra pregunta que importa en un servidor al que no se le ve la pantalla:
¿está encendido? Si esa hora es vieja, no.

QUÉ LLAVES VAN Y CUÁLES NO
==========================
La del PANEL sí: es la que abre los enlaces de la hoja, y quien ve el ERP ya
ve los mismos nombres, teléfonos y montos que el panel. Las de Meta, Claude,
Chatwoot y Google NO: con esas se gasta plata y se escribe por WhatsApp a
nombre del negocio, y Google guarda el historial de cada celda para siempre —
una clave pegada aquí un día queda ahí aunque se borre—. Para esas, la hoja
dice DÓNDE están y cómo cambiarlas.

Es una función pura: recibe lo que necesita y devuelve las filas. Escribirlas
es cosa del adaptador del ERP.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

#: El nombre de la hoja. Sin emojis ni tildes: se escribe en fórmulas y en
#: rangos «'CENTRO DE MANDO'!A1», y así no hay forma de equivocarse.
NOMBRE_DE_LA_HOJA = "CENTRO DE MANDO"

#: Cuántas filas se escriben SIEMPRE, rellenando con vacías. Si un día la
#: lista se acorta, lo que sobraba de la vez anterior se borra en vez de
#: quedarse ahí con datos viejos que parecen actuales.
FILAS = 44

#: Colombia no cambia de hora: UTC-5 todo el año. A mano porque Windows no
#: trae la base de zonas horarias y `ZoneInfo("America/Bogota")` revienta ahí.
HORA_COLOMBIA = timezone(timedelta(hours=-5), "America/Bogota")

#: Cada cuánto se reescribe (lo marca el ERP). Si «visto vivo» pasa de esto
#: con margen, el bot está apagado.
MINUTOS_ENTRE_VUELTAS = 10


def _hora(cuando: datetime) -> str:
    """Texto, no fecha: así Sheets no lo convierte ni lo cambia de formato."""
    local = cuando.astimezone(HORA_COLOMBIA)
    return f"{local:%d/%m/%Y · %H:%M} (hora Colombia)"


def filas_del_centro_de_mando(
    *,
    publico: str,
    local: str,
    token: str,
    chatwoot_local: str,
    arrancado: datetime,
    ahora: datetime,
    maquina: str,
    carpeta: Path,
    excel: str,
    langsmith: str = "",
    chatwoot_publico: str = "",
) -> list[list[str]]:
    """Lo que va en la hoja, fila por fila: [qué, enlace o dato, para qué]."""
    base = (publico or local).rstrip("/")
    t = f"?token={token}" if token else ""
    # Con dominio propio Chatwoot tiene el suyo (chat.lunajoyas.example); con
    # ngrok comparte el del bot.
    chatwoot = (chatwoot_publico or publico or chatwoot_local).rstrip("/")
    viejo = MINUTOS_ENTRE_VUELTAS + 5

    filas: list[list[str]] = [
        ["CENTRO DE MANDO · VentaBot · Luna Joyas", "", ""],
        [
            "Esta hoja la escribe el bot solo: cuando arranca y cada "
            f"{MINUTOS_ENTRE_VUELTAS} minutos. No la edites a mano — se sobrescribe.",
            "",
            "",
        ],
        ["", "", ""],
        ["QUÉ", "ENLACE O DATO", "PARA QUÉ"],
        ["— ¿ESTÁ ENCENDIDO? —", "", ""],
        [
            "El bot, visto vivo",
            _hora(ahora),
            f"Si esta hora tiene más de {viejo} minutos, el bot está APAGADO.",
        ],
        ["Arrancó", _hora(arrancado), "La última vez que se encendió."],
        [
            "Dónde corre",
            maquina,
            "El nombre del computador o servidor donde vive el bot.",
        ],
        ["Carpeta del programa", str(carpeta), "Ahí están los .cmd y el .env."],
        ["", "", ""],
        ["— ABRIR (clic en el enlace) —", "", ""],
        [
            "Centro de mando",
            f"{base}/panel/todo{t}",
            "TODO en una página: cómo va cada pieza y a un clic lo demás.",
        ],
        ["El taller", f"{base}/panel{t}", "Los pedidos en curso y sus botones."],
        [
            "Las conversaciones",
            f"{base}/panel/chats{t}",
            "Leer y contestarle a una clienta.",
        ],
        [
            "Chatwoot",
            chatwoot,
            "El CRM: etiquetas, notas y la app del celular (con su usuario).",
        ],
        [
            "Las métricas",
            f"{base}/panel/metricas{t}",
            "Capas de IA, escaladas, costo y latencia.",
        ],
        [
            "El registro del servidor",
            f"{base}/panel/registro{t}",
            "Lo último que hizo el bot, sin abrir ninguna ventana.",
        ],
        ["Dirección pública", publico or "(sin túnel)", "La que ve internet."],
        ["", "", ""],
        ["— PARA EL CELULAR —", "", ""],
        [
            "Cómo guardarlo",
            "Abre «Centro de mando» → menú del navegador → «Añadir a pantalla de inicio»",
            "Queda como una app. Si la dirección cambia, vuelve a esta hoja.",
        ],
        ["", "", ""],
        ["— LLAVES —", "", ""],
        [
            "Llave del panel (PANEL_TOKEN)",
            token or "(panel apagado)",
            "Va dentro de los enlaces de arriba. Si se filtra: cámbiala en el "
            ".env y reinicia; esta hoja se actualiza sola.",
        ],
        [
            "Claves de Meta, Claude, Chatwoot y Google",
            f"En el archivo {carpeta / '.env'} de «{maquina}»",
            "NO se escriben aquí: con ellas se gasta plata y se escribe por "
            "WhatsApp a nombre del negocio, y Google guarda el historial de cada "
            "celda para siempre.",
        ],
        ["", "", ""],
        ["— SERVICIOS DE AFUERA —", "", ""],
        [
            "Saldo de Claude (la IA)",
            "https://console.anthropic.com/settings/billing",
            "Si se acaba, el bot contesta «dame un momentico» a todo.",
        ],
        [
            "WhatsApp Business (Meta)",
            "https://business.facebook.com/latest/whatsapp_manager",
            "El número, las plantillas y el token de WhatsApp.",
        ],
        [
            "Auditoría de cada turno (LangSmith)",
            langsmith or "https://smith.langchain.com",
            "Qué pensó el bot en cada mensaje, uno por uno.",
        ],
        ["Excel de ventas", excel, "Se abre desde el computador donde corre el bot."],
        ["", "", ""],
        ["— SI ALGO FALLA —", "", ""],
        [
            "Revisar todo",
            "vb diagnostico",
            "En la carpeta del programa. Dice qué está mal y cómo arreglarlo.",
        ],
        ["Encender", "ENCENDER-BOT.cmd", "Doble clic en la carpeta del programa."],
        ["Apagar", "APAGAR-BOT.cmd", "Doble clic. Cierra todo lo del bot."],
    ]
    return filas + [["", "", ""]] * max(0, FILAS - len(filas))
