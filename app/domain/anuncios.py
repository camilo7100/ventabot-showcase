"""De qué anuncio llegó la clienta, y a qué pedido se le cuenta (ADR 0028).

════════════════════════════════════════════════════════════════════════════
PARA QUÉ
════════════════════════════════════════════════════════════════════════════
Marketing paga anuncios «Click to WhatsApp» en Instagram y Facebook. Meta le
dice cuánto costó cada CONVERSACIÓN, pero no cuál terminó en un anillo
vendido. Eso solo lo sabemos nosotros. Sin este dato, el anuncio que trae
muchas charlas y ninguna venta parece el mejor.

Cuando alguien toca el botón del anuncio, el primer mensaje que llega por el
webhook trae de qué anuncio venía. Aquí se guarda eso:

  · en la CLIENTA: el primer anuncio que la trajo (nunca cambia) y el último
    (cambia cada vez que vuelve por otro anuncio);
  · en el PEDIDO, cuando nace: el último anuncio de la clienta, si fue hace
    menos de `VENTANA_DE_ATRIBUCION_DIAS`. Se copia y no se vuelve a calcular:
    si después ella toca otro anuncio, el pedido que ya existía no se mueve.

Todo es puro: ni Meta, ni base de datos, ni Excel.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

#: Cuánto tiempo después del clic todavía se le cuenta el pedido al anuncio.
#: Una clienta que tocó un anuncio en enero y compra otro anillo en julio no
#: llegó por ese anuncio: contarlo inflaría la venta por anuncio. 28 días es
#: la ventana de clic más larga que ofrece Meta en el Administrador de
#: anuncios; con eso ningún pedido que Meta atribuiría se queda por fuera, y la
#: columna «Días desde el anuncio» del Excel deja filtrar a 7 si se quiere
#: comparar con la ventana por defecto de Meta.
VENTANA_DE_ATRIBUCION_DIAS = 28


class Referido(BaseModel):
    """Un toque de anuncio: de dónde llegó, y cuándo.

    Los nombres son nuestros, no los de Meta (eso lo traduce el adaptador del
    canal). Las URL de la imagen o el video del anuncio NO se guardan: caducan
    en horas y no sirven para nada después.
    """

    #: El id del anuncio (o de la publicación). Es la llave para cruzar con el
    #: Administrador de anuncios: ahí está el costo.
    anuncio_id: str
    #: «ad» (anuncio pagado) o «post» (publicación orgánica con el botón).
    tipo: str = ""
    #: El enlace al anuncio o a la publicación.
    url: str = ""
    #: El titular y el texto del anuncio: para leer la fila sin abrir Meta.
    titulo: str = ""
    texto: str = ""
    #: «image» o «video».
    medio: str = ""
    #: El id del CLIC. Es lo que hay que devolverle a Meta (Conversions API)
    #: para que sepa qué clic terminó en compra. Meta no lo manda en los
    #: anuncios de Estados de WhatsApp: puede venir vacío.
    ctwa_clid: str = ""
    #: Cuándo llegó el mensaje que lo traía.
    cuando: datetime


def con_toque(primero: Referido | None, toque: Referido) -> tuple[Referido, Referido]:
    """(primer toque, último toque) después de un toque nuevo.

    El primero no se pisa nunca: es lo que dice qué anuncio la CONSIGUIÓ.
    """
    return (primero or toque), toque


def toques_que_se_conservan(existente, nueva) -> dict:
    """Lo que hay que copiar de la clienta guardada a la que se va a guardar.

    Un `upsert` con una clienta recién armada (sin anuncios) borraría de dónde
    llegó. Los toques solo se escriben con `con_toque`; nunca se pierden por
    guardar otra cosa. Devuelve el `update` para `model_copy`.
    """
    if existente is None:
        return {}
    return {
        campo: getattr(existente, campo)
        for campo in ("primer_anuncio", "ultimo_anuncio")
        if getattr(nueva, campo) is None and getattr(existente, campo) is not None
    }


def anuncio_del_pedido(ultimo: Referido | None, nace: datetime) -> Referido | None:
    """El anuncio al que se le cuenta un pedido que nace en `nace`, o None.

    El último toque, si está dentro de la ventana. Un toque «del futuro» (el
    reloj del webhook adelantado unos segundos) también cuenta.
    """
    if ultimo is None:
        return None
    if (nace - ultimo.cuando).days >= VENTANA_DE_ATRIBUCION_DIAS:
        return None
    return ultimo


def dias_desde(referido: Referido | None, momento: datetime) -> int | None:
    """Días enteros entre el clic y `momento` (para el Excel)."""
    if referido is None:
        return None
    return max(0, (momento - referido.cuando).days)
