"""Varios modelos en fila: si uno no contesta, el siguiente; y se vuelve a empezar.

════════════════════════════════════════════════════════════════════════════
LO QUE PASÓ (29/09, 09:16)
════════════════════════════════════════════════════════════════════════════
Anthropic contestó «503 Service Unavailable» dos veces seguidas. El bot probó
UNA vez más, en menos de un segundo, y se rindió: la clienta recibió «dame un
momentico» y ese momentico nunca llegó. Había dicho «Sí» al resumen: iba a
pagar.

Una caída así dura segundos o minutos. Rendirse en un segundo es perder la
venta por impaciencia.

════════════════════════════════════════════════════════════════════════════
CÓMO
════════════════════════════════════════════════════════════════════════════
Se prueban los modelos EN ORDEN (Anthropic, y después el de respaldo cuando
Camilo lo ponga: GPT u otro). Si ninguno contesta, se espera un poco y se
vuelve a empezar por el primero, cada vez esperando algo más, hasta gastar la
`paciencia_s` del turno (la clienta está esperando). Si al final ninguno
contestó, se levanta el último error: quien llama deja el turno PENDIENTE y lo
reintenta en segundo plano hasta que alguno vuelva.

Un error que se repetiría igual (una petición mal armada, 400) no se reintenta
con ESE modelo en este turno; los caídos (5xx, límite de ritmo, red) sí.

Implementa el mismo `LLMPort` que cada modelo: el resto del sistema no se entera
de que hay más de uno.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from app.infra.trazas import etiquetar

log = logging.getLogger("ventabot.cadena")

#: Cuánto se espera entre una vuelta y la siguiente (segundos). Crece: una caída
#: de un segundo se recupera enseguida; una de un minuto, no.
ESPERAS_S = (2.0, 5.0, 10.0, 15.0)


def es_pasajero(exc: Exception) -> bool:
    """¿Vale la pena reintentar con ESTE modelo? 5xx, ritmo, red: sí. 4xx: no."""
    codigo = getattr(exc, "status_code", None)
    if isinstance(codigo, int):
        return codigo >= 500 or codigo in (408, 409, 429)
    # Sin código HTTP: red caída, tiempo agotado, respuesta que no encajó.
    return True


class CadenaDeModelos:
    """Implementa `LLMPort`: prueba los modelos en orden, y en vueltas."""

    acepta_contexto = True

    def __init__(
        self,
        modelos: list,
        *,
        paciencia_s: float = 35.0,
        dormir: Callable[[float], None] = time.sleep,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        if not modelos:
            raise ValueError("la cadena necesita al menos un modelo")
        self._modelos = list(modelos)
        self._paciencia = paciencia_s
        self._dormir = dormir
        self._reloj = reloj

    @property
    def model(self) -> str:
        """El nombre del primero (el que se usa cuando todo está bien)."""
        return " → ".join(getattr(m, "model", "?") for m in self._modelos)

    def extract(self, system_prompt, user_text, schema, **kw):
        inicio = self._reloj()
        descartados: set[int] = set()
        ultimo: Exception | None = None
        vuelta = 0
        while True:
            for i, modelo in enumerate(self._modelos):
                if i in descartados:
                    continue
                try:
                    resultado = modelo.extract(system_prompt, user_text, schema, **kw)
                except Exception as exc:
                    ultimo = exc
                    nombre = getattr(modelo, "model", "?")
                    if not es_pasajero(exc):
                        descartados.add(i)
                        log.warning("%s no sirve para este turno (%s)", nombre, exc)
                    else:
                        log.warning("%s no contestó (%s)", nombre, exc)
                    continue
                if vuelta or i:
                    log.info(
                        "contestó %s (vuelta %s)",
                        getattr(modelo, "model", "?"),
                        vuelta + 1,
                    )
                    # En LangSmith: filtrar los turnos que no contestó el
                    # principal (etiqueta «respaldo») o que tuvieron que insistir.
                    etiquetar("respaldo" if i else "", "reintento" if vuelta else "")
                return resultado
            if len(descartados) == len(self._modelos):
                break
            espera = ESPERAS_S[min(vuelta, len(ESPERAS_S) - 1)]
            if self._reloj() - inicio + espera > self._paciencia:
                break
            vuelta += 1
            log.warning(
                "ningún modelo contestó: otra vuelta en %.0f s (vuelta %s)",
                espera,
                vuelta + 1,
            )
            self._dormir(espera)
        assert ultimo is not None
        raise ultimo
