"""Adaptador de Bold (pasarela colombiana).

API: https://developers.bold.co/pagos-en-linea/api-link-de-pagos
Webhooks: https://developers.bold.co/webhook

Por qué Bold como primera opción:
  * Crea links por API (POST integrations.api.bold.co/online/link/v1)
  * Webhook firmado con HMAC-SHA256 en el header `x-bold-signature`
  * Dispersión en SEGUNDOS a la Cuenta Bold (Wompi es día hábil siguiente)
  * Soporta QR Bre-B en pagos en línea desde febrero de 2026

Tarifas (verifícalas en tu panel, cambian): desde 2,99% + $900 tarjeta,
2,89% + $900 PSE/billeteras/Bre-B.

REINTENTOS QUE DEBES SOPORTAR: Bold reintenta a 15 min, 1 h, 4 h, 8 h y 24 h,
y exige respuesta 200 en 2 segundos. Sin idempotencia, cinco confirmaciones
del mismo pago = cinco mensajes al cliente y posible doble avance de estado.

Wompi es equivalente; su ventaja es que el Web Checkout te deja definir tu
propia `reference` y firma de integridad:
    signature:integrity = SHA256(reference + amountInCents + currency + secret)
Su checksum de webhook va en el header `X-Event-Checksum` y reintenta 3 veces
(30 min, 3 h, 24 h).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from app.domain.ports import PaymentLink

BOLD_API = "https://integrations.api.bold.co/online/link/v1"


class BoldGateway:
    """Implementa `app.domain.ports.PaymentGateway`."""

    def __init__(self, identity_key: str, secret_key: str, callback_url: str) -> None:
        self._identity_key = identity_key
        self._secret = secret_key.encode()
        self._callback_url = callback_url

    # -- creación de link ---------------------------------------------------

    def create_link(
        self,
        *,
        reference: str,
        amount_cop: int,
        description: str,
        expires_in_hours: int = 72,
    ) -> PaymentLink:
        import httpx  # import perezoso: los tests no necesitan red

        expira = datetime.now(UTC) + timedelta(hours=expires_in_hours)
        cuerpo = {
            "amount_type": "CLOSE",
            "amount": {"currency": "COP", "total_amount": amount_cop},
            # `reference` (máx. 60 chars) ES tu ID de pedido. Es lo que hace
            # trivial la conciliación: el webhook te la devuelve tal cual.
            "reference": reference[:60],
            "description": description[:100],
            # Bold espera la expiración en Unix NANOSEGUNDOS (no segundos).
            "expiration_date": int(expira.timestamp() * 1_000_000_000),
            "callback_url": self._callback_url,
            "payment_methods": ["CREDIT_CARD", "PSE", "NEQUI"],
        }
        r = httpx.post(
            BOLD_API,
            headers={
                "Authorization": f"x-api-key {self._identity_key}",
                "Content-Type": "application/json",
            },
            json=cuerpo,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()["payload"]
        return PaymentLink(
            url=data["url"], reference=reference, gateway_id=data["payment_link"]
        )

    # -- verificación de webhook -------------------------------------------

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        """HMAC-SHA256 sobre el BODY CRUDO, resultado en Base64.

        DOS COSAS QUE NO SE NEGOCIAN:
          1. `raw_body` debe ser los bytes EXACTOS que llegaron. Si parseas el
             JSON y lo re-serializas, la firma nunca cuadra. Es el bug nº1 de
             integraciones de webhooks.
          2. `hmac.compare_digest`, no `==`. Comparación de tiempo constante.
        """
        esperado = base64.b64encode(
            hmac.new(self._secret, raw_body, hashlib.sha256).digest()
        ).decode()
        return hmac.compare_digest(esperado, signature or "")

    # -- re-consulta --------------------------------------------------------

    def fetch_transaction(self, transaction_id: str) -> dict:
        """Re-consulta la API. NUNCA confíes solo en el payload del webhook.

        Es la defensa contra replay y contra un webhook falsificado por alguien
        que obtuvo tu secreto de una versión anterior. Cuesta una llamada HTTP
        y te ahorra el fraude entero.
        """
        import httpx

        r = httpx.get(
            f"{BOLD_API}/{transaction_id}",
            headers={"Authorization": f"x-api-key {self._identity_key}"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def parse_event(raw_body: bytes) -> dict:
        """Normaliza el evento de Bold.

        Tipos: SALE_APPROVED, SALE_REJECTED, VOID_APPROVED, VOID_REJECTED.
        """
        data = json.loads(raw_body)
        payload = data.get("data", {})
        return {
            "event_id": data.get("id") or payload.get("payment_id", ""),
            "tipo": data.get("type", ""),
            "aprobado": data.get("type") == "SALE_APPROVED",
            "reference": payload.get("metadata", {}).get("reference")
            or payload.get("reference", ""),
            "transaction_id": payload.get("payment_id", ""),
            "monto_cop": int(payload.get("amount", {}).get("total", 0)),
        }


class FakeGateway:
    """Doble de prueba. Los links son deterministas: mismo reference, mismo link."""

    def __init__(self) -> None:
        self.links: dict[str, PaymentLink] = {}

    def create_link(
        self,
        *,
        reference: str,
        amount_cop: int,
        description: str,
        expires_in_hours: int = 72,
    ) -> PaymentLink:
        if reference not in self.links:
            self.links[reference] = PaymentLink(
                url=f"https://checkout.test/{reference}",
                reference=reference,
                gateway_id=f"LNK_{reference}",
            )
        return self.links[reference]

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        return signature == "valida"

    def fetch_transaction(self, transaction_id: str) -> dict:
        return {"id": transaction_id, "status": "APPROVED"}
