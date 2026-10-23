"""Lo que el bot contesta: una LISTA de mensajes, no uno.

════════════════════════════════════════════════════════════════════════════
POR QUÉ ESTO CAMBIA MÁS DE LO QUE PARECE
════════════════════════════════════════════════════════════════════════════
Hasta ahora el grafo producía exactamente un `OutboundMessage`. No era una
limitación de código: era el techo de lo que el bot podía decir. «Mira estos
ejemplos» + tres fotos + «todos se personalizan» es un solo acto de habla y
cuatro mensajes de WhatsApp, y no cabía.

Ese techo es la razón real por la que las imágenes del catálogo nunca
salieron. El nodo escribía `reply_imagen` en el estado y no había dónde
ponerlo: no existía un segundo mensaje.

════════════════════════════════════════════════════════════════════════════
POR QUÉ ES UN TIPO DEL DOMINIO Y NO UNA LISTA DE OutboundMessage
════════════════════════════════════════════════════════════════════════════
`OutboundMessage` ya sabe de canales, de plantillas de Meta y de claves de
idempotencia. El dominio no debería. Aquí se dice QUÉ se quiere decir —un
texto, una imagen— y el adaptador decide cómo se ve en WhatsApp y cómo se ve
en Instagram.

Las imágenes se nombran por su nombre LÓGICO ("muestrario_circones"). A qué
archivo corresponde y bajo qué URL pública se sirve lo resuelve el adaptador,
porque esa URL cambia cada vez que se reinicia el túnel y el dominio no puede
depender de eso.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tipo(str, Enum):
    TEXTO = "TEXTO"
    IMAGEN = "IMAGEN"
    #: Los videos del producto. Son los que más venden de todo el material:
    #: un anillo de plata con circones no se ve en una foto fija, se ve
    #: cuando le da la luz. Lía los manda a mano en cada cotización.
    VIDEO = "VIDEO"


@dataclass(frozen=True)
class Pieza:
    """Un mensaje suelto de la respuesta."""

    tipo: Tipo
    texto: str = ""
    #: Nombre lógico del archivo (imagen o video). Nunca una ruta ni una URL.
    imagen: str | None = None
    #: Botones. Vacío por defecto y así se queda: la conversación tiene que
    #: funcionar entera escribiendo. Existen para poder medir si ayudan,
    #: no porque el flujo dependa de ellos.
    opciones: tuple[dict, ...] = ()


@dataclass
class Respuesta:
    """Todo lo que el bot dice en este turno, en orden."""

    piezas: list[Pieza] = field(default_factory=list)
    #: Marca el turno para que un humano lo mire. No corta la conversación.
    escalar: bool = False
    #: Para el log. Es lo que se lee cuando algo salió raro.
    traza: list[str] = field(default_factory=list)
    #: QUÉ se dijo, en una palabra («pregunta:colores»). No es el texto: es
    #: el asunto. Sirve para saber, en el turno siguiente, que se está a
    #: punto de preguntar exactamente lo mismo otra vez.
    clave: str = ""
    #: Huella del texto que se HABRÍA dicho sin esquivar repeticiones. Es lo
    #: que se compara en el turno siguiente: si se guardara el texto ya
    #: variado, la segunda vez volvería a salir el original y el bot
    #: alternaría entre dos frases para siempre.
    huella: str = ""

    # -- construcción -------------------------------------------------------

    def decir(self, texto: str, *, opciones: tuple[dict, ...] = ()) -> Respuesta:
        if texto and texto.strip():
            self.piezas.append(Pieza(Tipo.TEXTO, texto=texto.strip(), opciones=opciones))
        return self

    def mostrar(self, imagen: str, *, pie: str = "") -> Respuesta:
        """Una imagen, opcionalmente con pie.

        El pie va DENTRO de la pieza y no como texto aparte porque WhatsApp
        lo manda junto: separarlos haría llegar dos notificaciones donde
        debería haber una.
        """
        self.piezas.append(Pieza(Tipo.IMAGEN, imagen=imagen, texto=pie))
        return self

    def reproducir(self, video: str, *, pie: str = "") -> Respuesta:
        """Un video, con pie opcional. Igual que `mostrar`, otro tipo."""
        self.piezas.append(Pieza(Tipo.VIDEO, imagen=video, texto=pie))
        return self

    def anotar(self, nota: str) -> Respuesta:
        self.traza.append(nota)
        return self

    def pedir_humano(self, texto: str) -> Respuesta:
        self.escalar = True
        return self.decir(texto)

    # -- lectura ------------------------------------------------------------

    @property
    def vacia(self) -> bool:
        return not self.piezas

    @property
    def texto_plano(self) -> str:
        """Todo el texto junto. Para los tests y para el log, no para enviar."""
        return "\n".join(p.texto for p in self.piezas if p.texto)

    def imagenes(self) -> list[str]:
        return [p.imagen for p in self.piezas if p.imagen]

    def adjuntos(self) -> list[tuple[str, str]]:
        """(tipo, nombre) de todo lo que no es texto. Para los tests y el log."""
        return [(p.tipo.value, p.imagen) for p in self.piezas if p.imagen is not None]
