"""Mirar las fotos que manda la clienta, y quedarse con lo que sirva.

Es el tramo 2 aplicado a imágenes. Hace tres cosas y ninguna más:

    1. baja el archivo             (`MediaPort`)
    2. se lo da al modelo de visión (`VisionPort`)
    3. traduce lo que vio a una `Interpretacion`  (`vision.entender`)

════════════════════════════════════════════════════════════════════════════
LA PISTA
════════════════════════════════════════════════════════════════════════════
Antes de mirar, se le dice al modelo qué estábamos esperando: si la compra
espera la talla, lo más probable es que sea el anillo con la regla. No obliga
a nada —una clienta manda el comprobante cuando le pedías la talla y hay que
reconocerlo igual— pero mirar buscando algo concreto le sube mucho el acierto
a un modelo pequeño.

Lo que se espera sale de lo que está VIVO: la compra en curso y los pedidos
ACTIVOS (`contexto.operativo`). Un pedido cerrado no espera nada, así que una
foto nunca se interpreta contra el pedido de agosto.

════════════════════════════════════════════════════════════════════════════
QUÉ SIGNIFICA UNA FOTO = FOTO + ESTADO + PENDIENTES
════════════════════════════════════════════════════════════════════════════
  1. Se mira con el lector básico, con la pista de lo pendiente.
  2. Si NO se entendió y la foto importa (hay un pago, una talla o unos
     colores pendientes), se vuelve a mirar con el lector potente.
  3. Si sigue sin entenderse:
       · solo hay UNA cosa que pueda ser (un pedido esperando el pago y nada
         más) -> se trata como esa, CON nota para una persona;
       · hay VARIAS -> se le pregunta a la clienta cuál es, y la referencia de
         la foto se guarda para volver a mirarla con la respuesta.

Un comprobante, se lea como se lea, nunca paga nada: deja el pedido EN
REVISIÓN, que es un estado que no produce ni despacha.

════════════════════════════════════════════════════════════════════════════
NUNCA SE BLOQUEA
════════════════════════════════════════════════════════════════════════════
Si no hay ojos, si el archivo no se puede bajar o si el modelo no entiende
nada, esto devuelve una interpretación con una nota para el panel y la
conversación sigue por donde iba. Una foto ilegible no puede dejar a nadie
sin respuesta: se guarda lo que se vio, se marca, y una persona lo mira.
"""

from __future__ import annotations

import logging

from app.domain import consumo
from app.domain.contexto import ContextoConversacional, TipoProceso
from app.domain.interpretacion import (
    Acto,
    DatosSueltos,
    Entidad,
    Interpretacion,
    RutaDeInterpretacion,
)
from app.domain.personalizacion import ColorCircon
from app.domain.vision import Hallazgo, TipoDeImagen, entender

log = logging.getLogger("ventabot.ojos")

#: Tipos de adjunto que tiene sentido mirar. Un audio o un sticker no.
MIRABLES = frozenset({"image", "document", "sticker"})

#: Lo que una foto puede resolver de lo pendiente.
UTILES = ("comprobante", "talla", "colores")


class Ojos:
    """Convierte adjuntos en `Interpretacion`. El único sitio que baja archivos."""

    def __init__(self, vision=None, media=None, vision_fuerte=None) -> None:
        self._vision = vision  # VisionPort, o None
        self._media = media  # MediaPort, o None
        #: El lector potente, solo para las fotos que importan y no se
        #: entendieron. Puede no existir.
        self._vision_fuerte = vision_fuerte

    # -- entrada ------------------------------------------------------------

    def mirar(
        self,
        media: list[dict],
        contexto: ContextoConversacional,
        *,
        pista: str | None = None,
    ) -> Interpretacion | None:
        """Lo que dicen las fotos de este mensaje, o None si no había ninguna."""
        adjuntos = [m for m in (media or []) if (m or {}).get("kind") in MIRABLES]
        if not adjuntos:
            return None

        posibles = self._posibles(contexto)
        if pista is None:
            pista = posibles[0] if posibles else ""
        crudos = [self._bajar(m) for m in adjuntos]

        with consumo.capa("vision"):
            hallazgos = [self._una(datos, pista, self._vision) for datos in crudos]
        leida = self._juntar([h for h in hallazgos if h is not None], pista)
        leida.ruta = RutaDeInterpretacion(
            capa="basico" if self._vision is not None else "reglas",
            motivo="vision" if self._vision is not None else "sin_lector",
        )

        if not _no_se_entendio(leida) or not posibles:
            return leida

        # 2. La foto importa y no se entendió: el lector potente.
        if self._vision_fuerte is not None and any(crudos):
            with consumo.capa("vision_fuerte"):
                otra = [self._una(d, pista, self._vision_fuerte) for d in crudos]
            segunda = self._juntar([h for h in otra if h is not None], pista)
            segunda.ruta = RutaDeInterpretacion(
                capa="fuerte",
                motivo="vision",
                escalado=True,
                motivo_escalada="foto_ambigua",
            )
            if not _no_se_entendio(segunda):
                return segunda
            leida.notas = list(dict.fromkeys([*leida.notas, *segunda.notas]))[:6]
            leida.ruta = segunda.ruta.model_copy(
                update={"motivo_escalada": "foto_ambigua:sin_mejora"}
            )

        # 3. Sigue sin entenderse. Decide el ESTADO si solo cabe una lectura;
        #    si caben varias, se pregunta.
        utiles = [p for p in posibles if p in UTILES]
        if utiles == ["comprobante"]:
            return _por_contexto_comprobante(leida)
        if len(utiles) >= 2:
            return _preguntar_que_es(leida, adjuntos[0], utiles)
        return leida

    # -- una foto -----------------------------------------------------------

    def _una(self, datos: bytes | None, pista: str, vision) -> Hallazgo | None:
        if datos is None or vision is None:
            return Hallazgo(
                tipo=TipoDeImagen.OTRA,
                revisar=["Mandó una foto que el sistema no pudo mirar: ábrela tú."],
            )
        return entender(vision.leer(datos, pista=pista))

    def _bajar(self, adjunto: dict) -> bytes | None:
        if self._media is None:
            return None
        referencia = adjunto.get("media_id") or adjunto.get("url")
        if not referencia:
            return None
        try:
            return self._media.download(referencia)
        except Exception as exc:
            log.warning("no se pudo bajar el adjunto (%s)", exc)
            return None

    # -- qué estábamos esperando -------------------------------------------

    @staticmethod
    def _posibles(contexto: ContextoConversacional) -> list[str]:
        """Lo que la foto PODRÍA ser, según lo que está vivo. En orden.

        El pago va primero: si le pedimos el comprobante, una foto es el
        comprobante aunque la compra siga esperando la talla.
        """
        posibles: list[str] = []
        operativo = getattr(contexto, "operativo", None)
        if contexto.abiertos(TipoProceso.PAGO_REPORTADO) or (
            operativo is not None and operativo.espera_comprobante()
        ):
            posibles.append("comprobante")
        for proceso in contexto.abiertos(TipoProceso.COMPRA):
            if proceso.faltan:
                posibles.append(proceso.faltan[0])
                break
        if operativo is not None and any(p.falta_talla for p in operativo.activos):
            posibles.append("talla")
        return list(dict.fromkeys(posibles))

    @staticmethod
    def _que_esperabamos(contexto: ContextoConversacional) -> str:
        """La pista principal: el hueco que el bot acaba de preguntar, o «»."""
        posibles = Ojos._posibles(contexto)
        return posibles[0] if posibles else ""

    # -- de lo que se vio a lo que significa -------------------------------

    def _juntar(self, hallazgos: list[Hallazgo], pista: str) -> Interpretacion:
        """Varias fotos en un mensaje son un solo mensaje. Se suman.

        Manda la primera que aporte algo: si llegan el comprobante y una foto
        del perro, lo que hay que atender es el comprobante.
        """
        datos = DatosSueltos()
        notas: list[str] = []
        tipos: list[TipoDeImagen] = []
        preguntas: list[str] = []

        for h in hallazgos:
            notas.extend(h.revisar)
            tipos.append(h.tipo)
            if h.para_preguntar:
                preguntas.append(h.para_preguntar)
            _volcar(h, datos)

        principal = _manda(tipos)
        acto, entidad = _que_es(principal, datos)
        return Interpretacion(
            acto=acto,
            entidad=entidad,
            datos=datos,
            confianza="ALTA" if datos.hay_algo() or datos.comprobante else "MEDIA",
            foto=principal.value,
            notas=notas[:6],
            foto_dice=preguntas[0] if preguntas else "",
        )


def _no_se_entendio(i: Interpretacion) -> bool:
    """La foto no dejó NADA: ni un tipo útil, ni un dato."""
    return (
        i.foto == TipoDeImagen.OTRA.value
        and not i.datos.hay_algo()
        and not i.datos.comprobante
    )


def _por_contexto_comprobante(leida: Interpretacion) -> Interpretacion:
    """Solo podía ser el comprobante. Se recibe como tal, y lo mira una persona.

    Recibirlo no paga nada: el pedido pasa a EN REVISIÓN. Si resulta que era
    otra foto, alguien lo ve en el panel y lo devuelve — eso cuesta un vistazo.
    Ignorarla cuesta una clienta que pagó y cree que nadie la leyó.
    """
    notas = [n for n in leida.notas if "ábrela tú" not in n]
    return leida.model_copy(
        update={
            "acto": Acto.INFORMAR,
            "entidad": Entidad.COMPROBANTE,
            "datos": leida.datos.model_copy(update={"comprobante": True}),
            "confianza": "MEDIA",
            "foto": TipoDeImagen.COMPROBANTE.value,
            "notas": [
                "Llegó una foto que no se pudo leer; por el estado del pedido "
                "(esperando un pago) se tomó como COMPROBANTE: verificar el pago "
                "en la cuenta y abrir la foto.",
                *notas,
            ][:6],
            "ruta": leida.ruta.model_copy(update={"motivo": "vision+estado"}),
        }
    )


#: Cómo se nombra cada posibilidad al preguntar qué es una foto.
_QUE_ES: dict[str, str] = {
    "comprobante": "el *comprobante* del pago",
    "talla": "la foto del anillo con la regla para la *talla*",
    "colores": "los *colores* que escogiste",
}


def _preguntar_que_es(
    leida: Interpretacion, adjunto: dict, posibles: list[str]
) -> Interpretacion:
    """Podía ser varias cosas. Se pregunta, y la referencia de la foto se guarda."""
    opciones = " o ".join(_QUE_ES[p] for p in dict.fromkeys(posibles))
    return leida.model_copy(
        update={
            "acto": Acto.CONVERSAR,
            "entidad": Entidad.NINGUNA,
            "foto": "AMBIGUA",
            "foto_dice": f"¡Recibí tu foto! 💕 ¿Me confirmas si es {opciones}?",
            "foto_pendiente": {
                k: adjunto.get(k) for k in ("kind", "media_id", "url") if adjunto.get(k)
            },
            "ruta": leida.ruta.model_copy(update={"motivo": "vision_ambigua"}),
        }
    )


#: Qué foto manda cuando llegan varias juntas. El dinero primero, siempre.
PRIORIDAD: tuple[TipoDeImagen, ...] = (
    TipoDeImagen.COMPROBANTE,
    TipoDeImagen.ANILLO_CON_REGLA,
    TipoDeImagen.CIRCONES_SENALADOS,
    TipoDeImagen.MASCOTA,
    TipoDeImagen.OTRA,
)


def _manda(tipos: list[TipoDeImagen]) -> TipoDeImagen:
    for candidato in PRIORIDAD:
        if candidato in tipos:
            return candidato
    return TipoDeImagen.OTRA


def _volcar(hallazgo: Hallazgo, datos: DatosSueltos) -> None:
    """Pasa lo que se vio a los campos que entiende el resto del sistema."""
    d = hallazgo.datos
    if d.get("comprobante"):
        datos.comprobante = True
        datos.monto_visto_cop = d.get("monto_visto_cop")
        datos.referencia_vista = d.get("referencia_vista")
    if d.get("talla") is not None:
        datos.talla = float(d["talla"])
        datos.diametro_mm = d.get("diametro_mm")
        datos.foto_clara = not d.get("talla_revisar", False)
    if isinstance(d.get("color_corazon"), ColorCircon):
        datos.color_corazon = d["color_corazon"]
    if isinstance(d.get("color_dedos"), ColorCircon):
        datos.color_dedos = d["color_dedos"]


def _que_es(tipo: TipoDeImagen, datos: DatosSueltos) -> tuple[Acto, Entidad]:
    """De qué habla esta foto, en el vocabulario de la conversación.

    Cuando la foto no dejó ningún dato aprovechable se devuelve OTRO, y no
    CONVERSAR: OTRO con una compra abierta hace que el bot vuelva a lo que
    estaba preguntando (ver `acciones.planificar`), que es exactamente lo que
    hay que hacer con una foto que no se entendió. CONVERSAR contestaría «con
    mucho gusto» y dejaría la compra parada.
    """
    if tipo is TipoDeImagen.COMPROBANTE:
        return Acto.INFORMAR, Entidad.COMPROBANTE
    if tipo is TipoDeImagen.ANILLO_CON_REGLA and datos.talla is not None:
        return Acto.INFORMAR, Entidad.TALLA
    if tipo is TipoDeImagen.CIRCONES_SENALADOS and (
        datos.color_corazon or datos.color_dedos
    ):
        return Acto.INFORMAR, Entidad.COLOR
    return Acto.OTRO, Entidad.NINGUNA
