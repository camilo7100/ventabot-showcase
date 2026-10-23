"""Nodo NLU: la ÚNICA puerta de entrada del LLM al sistema.

Lo que entra: texto libre del cliente.
Lo que sale: un `Intencion` de Pydantic con campos Enum cerrados. Nada más.

Tres capas de contención, de afuera hacia adentro:
  1. Comando literal (#humano) -> ni siquiera se llama al LLM.
  2. Constrained decoding: el modelo NO PUEDE emitir JSON inválido.
  3. Validación Pydantic contra el catálogo real -> un SKU alucinado se rechaza.

Y una política de reintentos ACOTADA: máximo 2 intentos, luego fallback.
Nunca bucles de auto-corrección infinitos.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from app.domain.models import Intencion, Intent
from app.domain.ports import LLMPort, ProductRepository
from app.graph.state import ConvState

MAX_REINTENTOS = 2

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "nlu_v1.txt"


def cargar_prompt() -> str:
    """Los prompts viven en ARCHIVOS versionados, no en strings dentro del código.

    Así puedes hacer diff, revisar cambios en PR, y correr el golden dataset
    contra dos versiones para comparar. Un prompt es código.
    """
    return _PROMPT_PATH.read_text(encoding="utf-8")


def make_nlu_node(llm: LLMPort, products: ProductRepository):
    """Fábrica del nodo. Recibe los PUERTOS, no implementaciones concretas.

    En tests le pasas un `FakeLLM` y un `InMemoryProductRepository` y el nodo
    corre sin red, en microsegundos.
    """

    skus_validos = {p.sku for p in products.list_active()}
    prompt_base = cargar_prompt()
    catalogo_txt = "\n".join(
        f"- {p.sku}: {p.nombre} ({p.precio_cop} COP)"
        for p in products.list_active()
        if p.categoria == "anillos"  # la cadena no se ofrece (03/10)
    )
    system_prompt = prompt_base.replace("{{CATALOGO}}", catalogo_txt)

    def nlu(state: ConvState) -> dict:
        texto = (state.get("inbound_text") or "").strip()

        # Sin texto (solo media): no gastes una llamada al LLM.
        if not texto:
            return {
                "intent": Intent.COMPROBANTE.value
                if state.get("inbound_media")
                else Intent.OTRO.value,
                "entities": {},
                "trace": ["nlu: sin texto, atajo"],
            }

        errores: list[str] = []
        for intento in range(MAX_REINTENTOS):
            sufijo = ""
            if errores:
                # Reinyectar el error de validación es la forma más efectiva de
                # corregir: el modelo ve exactamente qué rompió.
                sufijo = (
                    "\n\nTu respuesta anterior fue inválida. Error: "
                    + errores[-1]
                    + "\nCorrige y responde SOLO el JSON."
                )
            try:
                resultado = llm.extract(system_prompt + sufijo, texto, Intencion)
                assert isinstance(resultado, Intencion)

                # Validación contra la REALIDAD, no solo contra el tipo.
                # Un LLM alucina SKUs sintácticamente perfectos.
                if resultado.sku and resultado.sku not in skus_validos:
                    raise ValueError(f"SKU inexistente: {resultado.sku}")

                return {
                    "intent": resultado.tipo.value,
                    "entities": resultado.model_dump(exclude={"tipo"}, exclude_none=True),
                    "nlu_retries": intento,
                    "trace": [f"nlu: {resultado.tipo.value} (intento {intento + 1})"],
                }
            except (ValidationError, ValueError, KeyError) as exc:
                errores.append(str(exc)[:300])

        # Agotados los reintentos: fallback determinista. Nunca un tercer intento.
        return {
            "intent": Intent.OTRO.value,
            "entities": {},
            "needs_human": True,
            "error": (
                f"NLU falló {MAX_REINTENTOS} veces: {errores[-1] if errores else ''}"
            ),
            "nlu_retries": MAX_REINTENTOS,
            "trace": ["nlu: fallback -> humano"],
        }

    return nlu
