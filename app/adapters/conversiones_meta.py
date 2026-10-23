"""La venta, a Meta: un `Purchase` cuando Lía confirma un abono (13/10).

Camilo, 13/10 (con marketing): para que los anuncios de «clic a WhatsApp»
aprendan QUIÉN compra, cada abono confirmado va al dataset de mensajes de la
cuenta de WhatsApp del bot, unido al clic del anuncio (`ctwa_clid`, que llega en
el primer mensaje de la clienta: `referral.ctwa_clid`). Es el formato con el que
marketing mandó a mano la venta PED-2026-3277 (`events_received: 1`); el
`event_id` es el código del pedido, así que reenviarla no la duplica.

Sin `ctwa_clid` (no vino de un anuncio) no se manda nada. Nunca lanza: si Meta
falla, el pedido se mueve igual y queda en el registro.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

log = logging.getLogger("ventabot.conversiones")

API = "https://graph.facebook.com/v22.0"


def evento_de_compra(
    *,
    codigo: str,
    valor_cop: int,
    ctwa_clid: str,
    waba_id: str,
    cuando: datetime,
) -> dict:
    """El cuerpo que recibe Meta (función pura: se prueba sin red)."""
    momento = cuando if cuando.tzinfo else cuando.replace(tzinfo=UTC)
    return {
        "data": [
            {
                "event_name": "Purchase",
                "event_time": int(momento.timestamp()),
                "event_id": codigo,
                "action_source": "business_messaging",
                "messaging_channel": "whatsapp",
                "user_data": {
                    "whatsapp_business_account_id": waba_id,
                    "ctwa_clid": ctwa_clid,
                },
                "custom_data": {
                    "currency": "COP",
                    "value": int(valor_cop),
                    "order_id": codigo,
                },
            }
        ]
    }


class ConversionesDeMeta:
    """Manda las compras al dataset de mensajes del bot."""

    def __init__(self, dataset_id: str, token: str, waba_id: str) -> None:
        self._dataset = dataset_id
        self._token = token
        self._waba = waba_id

    def compra(
        self, *, codigo: str, valor_cop: int, ctwa_clid: str, cuando: datetime
    ) -> bool:
        """True si Meta la recibió. Nunca lanza."""
        if not ctwa_clid:
            return False
        import httpx

        cuerpo = evento_de_compra(
            codigo=codigo,
            valor_cop=valor_cop,
            ctwa_clid=ctwa_clid,
            waba_id=self._waba,
            cuando=cuando,
        )
        try:
            r = httpx.post(
                f"{API}/{self._dataset}/events",
                params={"access_token": self._token},
                json=cuerpo,
                timeout=15,
            )
        except Exception as exc:
            log.warning("la venta %s no llegó a Meta (%s)", codigo, type(exc).__name__)
            return False
        if not r.is_success:
            mensaje = ""
            try:
                mensaje = (r.json().get("error") or {}).get("message", "")
            except Exception:
                mensaje = r.text[:200]
            log.warning("Meta no recibió la venta %s: %s", codigo, mensaje)
            return False
        log.info("venta %s enviada a Meta (%s)", codigo, r.json().get("events_received"))
        return True
