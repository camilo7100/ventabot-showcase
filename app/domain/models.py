"""Modelos de dominio.

REGLA DE ORO DE ESTE PAQUETE:
    `app.domain` no importa NADA de `app.adapters`, `app.api` ni `app.graph`.
    Solo stdlib + pydantic. Si algún día necesitas importar un adaptador aquí,
    la arquitectura se rompió y la migración a SQL/SAP se volvió cara.

Puedes hacer cumplir esta regla en CI con `import-linter`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.domain.anuncios import Referido
from app.domain.envio import DatosDeEnvio
from app.domain.faq import Pregunta
from app.domain.personalizacion import (
    MAX_GRABADOS,
    ColorCircon,
    Personalizacion,
)


def now_utc() -> datetime:
    """Siempre UTC con zona. Nunca `datetime.now()` sin tz."""
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# Canales
# ---------------------------------------------------------------------------


class Channel(str, Enum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"


#: Prefijo corto y estable por canal. NO derivarlo cortando el nombre del canal:
#: "whatsapp"[:2] da "wh" y "wa:" es lo que usa el resto del sistema. Ese
#: descuadre de dos letras hacía que la ventana de 24 h se buscara con una clave
#: que no existía, y el despachador creía que estaba cerrada SIEMPRE.
PREFIJO_CANAL: dict[Channel, str] = {
    Channel.WHATSAPP: "wa",
    Channel.INSTAGRAM: "ig",
}


def conversation_id(channel: Channel, channel_user_id: str) -> str:
    """El identificador de conversación. Es también el `thread_id` de LangGraph.

    Un único sitio que lo construye = imposible que dos partes del sistema
    usen claves distintas para la misma conversación.

    ⚠️ LangGraph exige que el thread_id mida menos de 255 caracteres.
    """
    return f"{PREFIJO_CANAL[channel]}:{channel_user_id}"[:254]


# ---------------------------------------------------------------------------
# Mensajes canónicos: el contrato que hace intercambiables los canales
# ---------------------------------------------------------------------------


class MediaRef(BaseModel):
    """Referencia a un archivo adjunto.

    WhatsApp entrega un `media_id` y hay que hacer 2 llamadas con token para
    bajarlo (la URL expira en 5 minutos). Instagram entrega una URL de CDN
    directa sin token. Por eso los dos campos son opcionales: el adaptador
    llena el que corresponda y `download()` del MediaPort resuelve la diferencia.
    """

    #: Los cinco primeros traen un ARCHIVO. Los otros no traen nada que bajar,
    #: pero son algo que ella mandó y que Lía tiene que ver (27/09): antes
    #: salían todos como «[adjunto]» y había que adivinar qué era.
    #:   · unsupported: WhatsApp no le pasa al bot ni el archivo ni el enlace
    #:     (error 131051 de Meta: foto o video «de una sola vista», encuestas,
    #:     eventos… Meta no dice cuál);
    #:   · reaction: reaccionó con un emoji a un mensaje;
    #:   · location / contacts: compartió una ubicación o un contacto.
    kind: Literal[
        "image",
        "document",
        "audio",
        "video",
        "sticker",
        "unsupported",
        "reaction",
        "location",
        "contacts",
    ]
    media_id: str | None = None
    url: str | None = None
    mime_type: str | None = None
    sha256: str | None = None
    #: El nombre del archivo, si lo trae (un PDF sí; una foto no).
    filename: str | None = None
    #: Lo que dice, para los que no traen archivo: el emoji de la reacción, la
    #: dirección de la ubicación, el nombre y el teléfono del contacto.
    detalle: str | None = None


#: Cómo se ve cada adjunto en Chatwoot y en el panel cuando no hay archivo que
#: mostrar (o mientras llega). Nunca «[adjunto]» a secas.
_ETIQUETA_ADJUNTO: dict[str, str] = {
    "image": "📷 Foto",
    "document": "📄 Documento",
    "audio": "🎤 Nota de voz",
    "video": "🎬 Video",
    "sticker": "🙂 Sticker",
    "location": "📍 Ubicación",
    "contacts": "👤 Contacto",
    "reaction": "Reaccionó",
    "unsupported": (
        "⚠️ Mandó algo que WhatsApp no le deja ver al bot (suele ser una foto o "
        "un video «de una sola vista», una encuesta o un evento). Pídele que lo "
        "mande como foto o mensaje normal"
    ),
}


def etiqueta_de_adjunto(kind: str, detalle: str | None = None, nombre: str = "") -> str:
    """«📄 Documento · cotizacion.pdf», «Reaccionó ❤️», «📍 Ubicación · Cra 7…»."""
    base = _ETIQUETA_ADJUNTO.get(kind, "📎 Archivo")
    if kind == "reaction":
        return f"{base} {detalle or ''} a un mensaje".replace("  ", " ")
    extra = " · ".join(x for x in (nombre, detalle or "") if x)
    return f"{base} · {extra}" if extra else base


def etiqueta_de_mensaje(texto: str | None, media) -> str:
    """El texto de un mensaje entrante para Chatwoot, el panel y el log.

    Con texto, el texto. Sin texto, qué mandó: «📷 Foto», «🎤 Nota de voz»…
    `media` son `MediaRef` o sus `model_dump()`.
    """
    if (texto or "").strip():
        return texto or ""
    partes = []
    for m in media or []:
        d = m if isinstance(m, dict) else m.model_dump()
        partes.append(
            etiqueta_de_adjunto(
                d.get("kind") or "", d.get("detalle"), d.get("filename") or ""
            )
        )
    return "\n".join(partes) or "(mensaje vacío)"


class InboundMessage(BaseModel):
    """Todo mensaje entrante, venga del canal que venga, se ve así."""

    channel: Channel
    external_message_id: str  # clave de deduplicación
    conversation_id: str  # == thread_id de LangGraph
    sender_id: str  # wa_id o IGSID
    sender_name: str | None = None
    text: str | None = None
    media: list[MediaRef] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=now_utc)
    raw: dict = Field(default_factory=dict)  # payload original, para debugging
    #: De qué anuncio llegó, si este mensaje vino de tocar un anuncio «Click to
    #: WhatsApp» (solo el primero de la charla lo trae). Ver
    #: `app/domain/anuncios.py`.
    referido: Referido | None = None
    #: Si este mensaje es una RÁFAGA fundida (`app/workers/agrupador.py`), los
    #: mensajes originales, en orden. Cada uno se guarda y se copia a Chatwoot
    #: por separado —como los escribió ella—; el turno los lee juntos.
    partes: list[InboundMessage] = Field(default_factory=list)


class Option(BaseModel):
    """Una opción presentable: botón en WhatsApp, fila de lista, quick reply..."""

    id: str
    title: str  # WhatsApp: máx. 20 chars en botón, 24 en fila de lista
    description: str | None = None  # solo listas


class OutboundMessage(BaseModel):
    """Mensaje saliente ABSTRACTO.

    El dominio pide "un texto con 5 opciones". El adaptador decide cómo se ve:
      - WhatsApp  -> interactive.list (o buttons si son <= 3)
      - Instagram -> texto numerado + quick replies (no tiene listas)

    El dominio nunca sabe la diferencia. Ese es el punto.
    """

    channel: Channel
    to: str
    kind: Literal["text", "options", "image", "video", "cta_url", "template"] = "text"
    text: str = ""
    options: list[Option] = Field(default_factory=list)
    media_url: str | None = None
    cta_url: str | None = None
    cta_label: str | None = None
    template_name: str | None = None
    template_params: dict = Field(default_factory=dict)
    idempotency_key: str = Field(default_factory=new_id)
    #: A qué conversación pertenece. El despachador lo necesita para saber si
    #: la ventana de 24 h está abierta.
    conversation_id: str | None = None
    #: Programado para más tarde (la disculpa de las 8 a. m.): a Chatwoot se
    #: copia cuando SALE, no al encolarlo. Así queda en su sitio y nunca se ve
    #: un mensaje que al final no salió (Jannet, 17/10).
    copiar_al_salir: bool = False


# ---------------------------------------------------------------------------
# Negocio
# ---------------------------------------------------------------------------


class Product(BaseModel):
    sku: str
    nombre: str
    descripcion: str = ""
    precio_cop: int = Field(ge=0)  # ENTERO. Nunca float para dinero.
    iva_pct: Decimal = Decimal("0.19")
    dias_produccion: int = 7
    dias_produccion_max: int | None = None  # "10 a 15 días": este es el 15
    anticipo_pct: Decimal = Decimal("0.50")
    #: Abono en PESOS. Si está puesto, gana sobre `anticipo_pct`.
    #:
    #: Lía cobra $60.000 para arrancar la fabricación, cueste el anillo
    #: $200.000 o $300.000: es lo que cuesta la plata que se funde, no una
    #: fracción del precio. Modelarlo como porcentaje obligaba a inventar un
    #: porcentaje distinto por producto para que diera la misma cifra, y a la
    #: primera subida de precio el abono se movía solo.
    anticipo_fijo_cop: int | None = Field(default=None, ge=0)
    #: Cuántas huellitas trae. Define cuántos pares de colores hay que pedir.
    huellitas: int = 0
    #: «anillos» o «cadenas» (03/10). La asesora vende los anillos; la cadena
    #: solo si la clienta pregunta por ella. Los precios por huellitas son de
    #: los anillos: una cadena de 1 huellita no puede pisar el del anillo de 1.
    categoria: str = "anillos"
    activo: bool = True
    imagen_url: str | None = None


class Customer(BaseModel):
    id: str = Field(default_factory=new_id)
    channel: Channel
    channel_user_id: str
    nombre: str | None = None
    telefono: str | None = None
    email: str | None = None
    ciudad: str | None = None
    direccion: str | None = None
    documento: str | None = None  # para facturación DIAN
    # --- habeas data (Ley 1581 de 2012) ---
    consent_at: datetime | None = None
    consent_text_version: str | None = None
    #: El primer anuncio que la trajo (no cambia nunca) y el último que tocó.
    #: Ver `app/domain/anuncios.py`.
    primer_anuncio: Referido | None = None
    ultimo_anuncio: Referido | None = None
    created_at: datetime = Field(default_factory=now_utc)


class OrderItem(BaseModel):
    sku: str
    nombre: str
    cantidad: int = Field(ge=1)
    precio_unitario_cop: int = Field(ge=0)
    #: Lo que la clienta eligió. Vacío mientras todavía se está preguntando.
    personalizacion: Personalizacion = Field(default_factory=Personalizacion)

    @property
    def subtotal_cop(self) -> int:
        return self.precio_unitario_cop * self.cantidad


class Order(BaseModel):
    id: str = Field(default_factory=new_id)
    codigo: str  # legible: PED-2026-0417. Es la `reference` de la pasarela.
    customer_id: str
    estado: str  # ver app.domain.order_state.OrderState
    items: list[OrderItem] = Field(default_factory=list)

    subtotal_cop: int = 0
    iva_cop: int = 0
    envio_cop: int = 0
    #: El flete que la clienta le paga al transportador al recibir. NO entra
    #: en `total_cop` (por eso son dos campos): el total es lo que se le cobra
    #: a ella, y el flete lo cobra COORDINADORA en la puerta.
    #:
    #: Se guarda EN EL PEDIDO y no se recalcula al mostrarlo porque las
    #: tarifas suben: un pedido cotizado en marzo tiene que seguir diciendo lo
    #: que se le prometió en marzo, aunque `data/fletes.csv` ya diga otra cosa.
    envio_contraentrega_cop: int = 0
    total_cop: int = 0
    anticipo_cop: int = 0
    saldo_cop: int = 0
    anticipo_pagado_cop: int = 0
    saldo_pagado_cop: int = 0

    #: A dónde va y a nombre de quién. Se llena durante la conversación, antes
    #: de nombrar el abono: sin dirección no se despacha nada, y descubrirlo
    #: diez días después —con el anillo hecho— es como se pierde un anillo.
    envio: DatosDeEnvio = Field(default_factory=DatosDeEnvio)
    fecha_estimada_entrega: datetime | None = None
    #: Nombres de archivo de las fotos del anillo terminado. Solo el NOMBRE:
    #: la URL completa depende del túnel del día, y guardarla haría que las
    #: fotos de ayer apuntaran a una dirección muerta.
    fotos: list[str] = Field(default_factory=list)
    notas: str = ""
    #: El anuncio al que se le cuenta esta venta: el último que tocó la
    #: clienta, copiado al nacer el pedido (`anuncios.anuncio_del_pedido`).
    #: None = no llegó por un anuncio, o fue hace demasiado.
    anuncio: Referido | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)

    @field_validator("total_cop", "anticipo_cop", "saldo_cop")
    @classmethod
    def _no_negativos(cls, v: int) -> int:
        if v < 0:
            raise ValueError("los montos no pueden ser negativos")
        return v


class OrderEvent(BaseModel):
    """Log de auditoría APPEND-ONLY. Nunca se actualiza ni se borra.

    Es tu única defensa el día que un cliente diga "yo sí pagué".
    """

    id: str = Field(default_factory=new_id)
    order_id: str
    estado_anterior: str | None
    estado_nuevo: str
    actor: str  # "bot" | "webhook:bold" | "operador:camilo" | "sistema"
    motivo: str = ""
    payload: dict = Field(default_factory=dict)
    idempotency_key: str  # UNIQUE: evita registrar dos veces la misma transición
    created_at: datetime = Field(default_factory=now_utc)


class PaymentKind(str, Enum):
    ANTICIPO = "ANTICIPO"
    SALDO = "SALDO"


class PaymentStatus(str, Enum):
    PENDIENTE = "PENDIENTE"
    APROBADO = "APROBADO"
    RECHAZADO = "RECHAZADO"
    EN_REVISION = "EN_REVISION"  # comprobante por imagen, sin conciliar


class Payment(BaseModel):
    id: str = Field(default_factory=new_id)
    order_id: str
    tipo: PaymentKind
    metodo: str = "LINK"  # LINK_BOLD | LINK_WOMPI | TRANSFERENCIA | EFECTIVO
    estado: PaymentStatus = PaymentStatus.PENDIENTE

    monto_esperado_cop: int  # incluye los dígitos únicos si aplica
    monto_recibido_cop: int = 0

    gateway_reference: str | None = None  # la `reference` que TÚ generaste
    gateway_transaction_id: str | None = None  # el id que devuelve la pasarela
    payment_link_url: str | None = None

    # --- si vino por imagen ---
    comprobante_media_url: str | None = None
    comprobante_hash_sha256: str | None = None
    comprobante_datos_extraidos: dict = Field(default_factory=dict)

    verificado_por: str | None = None  # WEBHOOK | EXTRACTO | operador:nombre
    verificado_at: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)


# ---------------------------------------------------------------------------
# Salida estructurada del LLM: el espacio de decisión CERRADO
# ---------------------------------------------------------------------------


class Intent(str, Enum):
    SALUDO = "SALUDO"
    CATALOGO = "CATALOGO"
    COTIZAR = "COTIZAR"
    CONFIRMAR = "CONFIRMAR"
    ESTADO = "ESTADO"
    PAGO = "PAGO"
    COMPROBANTE = "COMPROBANTE"
    QUEJA = "QUEJA"
    HUMANO = "HUMANO"
    #: Una de las preguntas de siempre: material, garantía, envío, pagos…
    #: La respuesta sale palabra por palabra de `app.domain.faq`.
    PREGUNTA = "PREGUNTA"
    #: Habla de la talla: la dice, la pregunta, o dice que no la sabe.
    TALLA = "TALLA"
    #: Está eligiendo colores o dando los nombres del grabado.
    PERSONALIZAR = "PERSONALIZAR"
    OTRO = "OTRO"


class Intencion(BaseModel):
    """Lo ÚNICO que el LLM puede devolver en el nodo NLU.

    Todos los campos de control son `Literal`/`Enum` con dominio cerrado.
    Un `str` libre en un campo de control reabre la puerta al caos.
    """

    tipo: Intent
    sku: str | None = None
    cantidad: int | None = Field(default=None, ge=1, le=500)
    ciudad: str | None = None
    #: Solo tiene sentido cuando `tipo` es PREGUNTA. Cerrado por Enum: el
    #: modelo no puede inventar una pregunta que no tenga respuesta escrita.
    pregunta: Pregunta = Pregunta.NINGUNA
    confianza: Literal["ALTA", "MEDIA", "BAJA"] = "MEDIA"

    model_config = {"use_enum_values": False}


# ---------------------------------------------------------------------------
# Esquemas de RANURA (slot filling).
#
# No son un solo esquema gigante a propósito. Cuando la conversación ya está
# esperando algo concreto —los colores, el grabado, la talla— se le pide al
# modelo EXACTAMENTE eso y nada más. Un esquema pequeño con tres campos lo
# acierta un modelo de 3B; uno de quince campos no.
#
# Es la misma idea del resto del proyecto: no le preguntes al modelo lo que ya
# sabes. Si el pedido está esperando colores, no hace falta que el modelo
# vuelva a decidir si esto es un saludo.
# ---------------------------------------------------------------------------


class RespuestaTalla(BaseModel):
    """Cuando la clienta habla de su talla."""

    #: La sabe y la dijo. `None` si no dio un número.
    talla: float | None = Field(default=None, ge=3, le=15)
    #: Dijo explícitamente que NO la sabe, o pidió la guía.
    necesita_guia: bool = False


class MedicionFoto(BaseModel):
    """Lo ÚNICO que el modelo de visión saca de la foto del anillo con regla.

    Ojo con lo que NO está aquí: la talla. El modelo mide, Python convierte
    (ver `app.domain.tallas`). Si el modelo devolviera la talla directamente,
    un error de lectura y un error de conversión serían indistinguibles.
    """

    diametro_mm: float | None = Field(default=None, ge=5, le=60)
    #: Falso si el anillo está torcido, borroso, sin regla, o si lo que se ve
    #: es el borde exterior en vez del interior.
    foto_clara: bool = False


class RespuestaColores(BaseModel):
    """Los colores de UNA huellita. Se pregunta una por una."""

    corazon: ColorCircon | None = None
    dedos: ColorCircon | None = None


class RespuestaGrabado(BaseModel):
    """Los nombres que van grabados dentro del aro."""

    nombres: list[str] = Field(default_factory=list, max_length=MAX_GRABADOS)
    #: Dijo que no quiere grabado. Distinto de "todavía no contestó".
    sin_grabado: bool = False


class DatosComprobante(BaseModel):
    """Salida del LLM de visión al leer un comprobante.

    OJO: esto NO prueba nada. Un comprobante editado se lee perfecto.
    Sirve para PRE-LLENAR un caso de revisión, nunca para aprobar un pago.
    """

    monto_cop: int | None = Field(default=None, ge=0)
    fecha_hora: str | None = None
    entidad: str | None = None  # Nequi, Bancolombia, Daviplata...
    ultimos4_destino: str | None = None
    referencia: str | None = None
    legible: bool = True
