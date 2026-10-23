"""Carga y valida `config/reglas.yaml`.

Las reglas de negocio son DATOS, no código: cambiarlas no requiere tocar Python
ni volver a desplegar. Pero sí se validan al arrancar, para que un typo en el
YAML no se convierta en un cobro mal calculado.

`marcadores_por_definir()` te dice qué sigue con un valor supuesto por mí.
"""

from __future__ import annotations

import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

MARCADOR = "[POR DEFINIR]"


class Negocio(BaseModel):
    nombre: str
    nit: str
    ciudad_origen: str
    zona_horaria: str = "America/Bogota"
    moneda: str = "COP"
    whatsapp_display_name: str


class Horario(BaseModel):
    dias_habiles: list[int]
    hora_inicio: str
    hora_fin: str
    sabado_hora_fin: str


class Impuestos(BaseModel):
    iva_pct: Decimal = Field(ge=0, le=1)
    responsable_de_iva: bool
    incluir_iva_en_precio_mostrado: bool


class Pagos(BaseModel):
    anticipo_pct_default: Decimal = Field(ge=0, le=1)
    redondeo_anticipo_cop: int = Field(ge=1)
    vigencia_link_horas: int = Field(ge=1)
    vigencia_cotizacion_horas: int = Field(ge=1)
    recordatorio_anticipo_horas: list[int]
    recordatorio_saldo_horas: list[int]
    cancelar_por_falta_de_anticipo_horas: int
    metodos_habilitados: list[str]
    permitir_transferencia_para_anticipo: bool
    permitir_transferencia_para_saldo: bool
    umbral_verificacion_manual_cop: int = Field(ge=0)
    no_despachar_contra_comprobante_dias: list[int]
    usar_monto_con_digitos_unicos: bool


class Envios(BaseModel):
    costo_default_cop: int = Field(ge=0)
    envio_gratis_desde_cop: int = Field(ge=0)
    transportadora_default: str


class Produccion(BaseModel):
    dias_produccion_default: int = Field(ge=0)
    dias_transporte_default: int = Field(ge=0)
    colchon_dias: int = Field(ge=0)
    capacidad_pedidos_simultaneos: int = Field(ge=0)


class Conversacion(BaseModel):
    fallos_nlu_antes_de_handoff: int = Field(ge=1)
    duracion_handoff_horas: int = Field(ge=1)
    max_productos_por_mensaje: int = Field(ge=1, le=10)  # WhatsApp: máx 10 filas
    timeout_conversacion_horas: int = Field(ge=1)
    cantidad_maxima_automatica: int = Field(ge=1)
    descuento_maximo_automatico_pct: Decimal = Field(ge=0, le=1)


class DatosPersonales(BaseModel):
    version_politica: str
    url_politica: str
    pedir_consentimiento_en_primer_contacto: bool
    retencion_chats_meses: int = Field(ge=1)
    retencion_comprobantes_meses: int = Field(ge=1)


class Reglas(BaseModel):
    negocio: Negocio
    horario: Horario
    impuestos: Impuestos
    pagos: Pagos
    envios: Envios
    produccion: Produccion
    conversacion: Conversacion
    datos_personales: DatosPersonales

    @field_validator("pagos")
    @classmethod
    def anticipo_coherente(cls, v: Pagos) -> Pagos:
        if v.permitir_transferencia_para_anticipo:
            # No es un error, pero sí una decisión de riesgo consciente.
            # Ver PLAN_MAESTRO §6.3: el fraude con comprobantes falsos ataca
            # exactamente este punto.
            pass
        return v


def marcadores_por_definir(path: Path) -> list[tuple[int, str]]:
    """Devuelve (línea, texto) de cada regla que sigue con un valor supuesto."""
    out = []
    for i, linea in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if MARCADOR in linea:
            out.append((i, re.sub(r"\s+", " ", linea.strip())))
    return out


@lru_cache(maxsize=1)
def cargar_reglas(path: Path | None = None) -> Reglas:
    from app.infra.settings import get_settings

    ruta = path or get_settings().reglas_path
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    return Reglas.model_validate(datos)
