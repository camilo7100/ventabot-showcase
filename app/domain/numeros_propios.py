"""Los números a los que el bot solo les contesta en el acto (Camilo, 19/10).

«Me enviaste a mi personal recordatorios y esto no es útil.» Los de Camilo y
el del negocio, igual que los inventados de las pruebas: el bot les contesta
cuando escriben, y NADA más. Ni recordatorios, ni la disculpa de las 8 a. m.,
ni plantillas, ni avisos al celular, ni ventas a Meta, ni el tablero.
"""

from __future__ import annotations

#: El personal de Camilo y el 317 (el número viejo del negocio).
NUMEROS_PROPIOS = frozenset({"573001110001", "573001110002"})
#: Los números inventados de las pruebas (5700000000xx).
PREFIJO_DE_PRUEBA = "5700000000"


def solo_respuesta_inmediata(conv_o_numero: str) -> bool:
    """¿Es de prueba o de la casa? Entonces nada programado ni automático."""
    numero = (conv_o_numero or "").rsplit(":", 1)[-1]
    return numero.startswith(PREFIJO_DE_PRUEBA) or numero in NUMEROS_PROPIOS
