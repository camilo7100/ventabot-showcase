"""El banco de plantillas por situación (Camilo, 22/10).

Cada SITUACIÓN («reenviar los datos de pago», «pedido liberado por falta de abono»)
es un grupo con varias plantillas alternativas, en orden de preferencia. Se usa la
PRIMERA que Meta tenga aprobada y a la que se le puedan llenar todas las
variables. Esto es solo el selector: no manda nada, y un grupo no se usa hasta que
Camilo lo prende (`activos`, por defecto ninguno).

Las plantillas se escriben con {{1}}, {{2}}…; cada una trae el ROL de cada
variable en `variables` («nombre», «monto», «codigo»…). Quien la manda pone los
valores por rol. Puro: se prueba sin red.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.domain.plantilla_de_emergencia import SIN_NOMBRE, primer_nombre

#: La foto de la cabecera, cuando la plantilla lleva imagen: va con este rol.
ROL_IMAGEN = "imagen"
_VARIABLE = re.compile(r"\{\{(\d+)\}\}")


@dataclass(frozen=True)
class Plantilla:
    nombre: str
    categoria: str
    cuerpo: str
    variables: tuple[str, ...] = ()
    botones: tuple[str, ...] = ()
    #: «IMAGE» si lleva foto arriba; None si no.
    encabezado: str | None = None

    def roles(self) -> tuple[str, ...]:
        """Todo lo que hay que tener para mandarla (la foto cuenta)."""
        return (*self.variables, *((ROL_IMAGEN,) if self.encabezado == "IMAGE" else ()))

    def faltan(self, valores: Mapping[str, str]) -> list[str]:
        return [r for r in self.roles() if not str(valores.get(r) or "").strip()]


@dataclass(frozen=True)
class Grupo:
    id: str
    situacion: str
    #: «dentro» (texto libre), «fuera» (solo plantilla) o «ambas».
    ventana: str
    #: Depende de una decisión de negocio pendiente: no se usa.
    bloqueada: bool
    #: Los nombres, en orden de preferencia.
    orden: tuple[str, ...]
    #: Los que ya existían y están en uso (nunca se borran).
    existentes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Escogida:
    """Lo que se manda: la plantilla, su texto ya con los valores y los
    parámetros posicionales que Meta espera."""

    grupo: str
    plantilla: Plantilla
    texto: str
    parametros: dict[str, str]


class Banco:
    def __init__(self, plantillas: Mapping[str, Plantilla], grupos: Mapping[str, Grupo]):
        self.plantillas = dict(plantillas)
        self.grupos = dict(grupos)

    @classmethod
    def desde_json(cls, ruta: Path) -> Banco:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        plantillas = {
            t["nombre"]: Plantilla(
                nombre=t["nombre"],
                categoria=t["categoria"],
                cuerpo=t["cuerpo"],
                variables=tuple(t.get("variables") or ()),
                botones=tuple(t.get("botones") or ()),
                encabezado=t.get("encabezado") or None,
            )
            for t in datos["plantillas"]
        }
        grupos = {
            g["grupo"]: Grupo(
                id=g["grupo"],
                situacion=g.get("situacion", ""),
                ventana=g.get("ventana", "ambas"),
                bloqueada=bool(g.get("bloqueada")),
                orden=tuple(o["nombre"] for o in g["orden"]),
                existentes=frozenset(
                    o["nombre"] for o in g["orden"] if o.get("existente")
                ),
            )
            for g in datos["grupos"]
        }
        return cls(plantillas, grupos)

    # -- escoger ------------------------------------------------------------

    def escoger(
        self,
        grupo_id: str,
        estados: Mapping[str, str],
        valores: Mapping[str, str],
    ) -> Escogida | None:
        """La primera plantilla del grupo que Meta tiene APROBADA y a la que se le
        pueden llenar todas las variables; None si ninguna sirve.

        Si a la primera le falta un dato (no se sabe el código del pedido), se
        pasa a la siguiente, que puede necesitar menos. Nunca se manda una
        plantilla con un hueco ni con un valor inventado."""
        grupo = self.grupos.get(grupo_id)
        if grupo is None or grupo.bloqueada:
            return None
        for nombre in grupo.orden:
            plantilla = self.plantillas.get(nombre)
            if plantilla is None or estados.get(nombre) != "APPROVED":
                continue
            if plantilla.faltan(valores):
                continue
            return armar(grupo_id, plantilla, valores)
        return None

    def por_que_no(
        self, grupo_id: str, estados: Mapping[str, str], valores: Mapping[str, str]
    ) -> str:
        """Para el aviso cuando no se pudo escoger: qué le pasó a cada una."""
        grupo = self.grupos.get(grupo_id)
        if grupo is None:
            return f"el grupo {grupo_id} no existe"
        if grupo.bloqueada:
            return f"el grupo {grupo_id} está bloqueado por una decisión pendiente"
        partes = []
        for nombre in grupo.orden:
            p = self.plantillas.get(nombre)
            estado = estados.get(nombre) or "no existe en Meta"
            if p is not None and estado == "APPROVED" and (falta := p.faltan(valores)):
                partes.append(f"{nombre}: aprobada, pero falta {', '.join(falta)}")
            else:
                partes.append(f"{nombre}: {estado}")
        return "; ".join(partes)


def armar(grupo: str, plantilla: Plantilla, valores: Mapping[str, str]) -> Escogida:
    """El texto con los valores puestos y los parámetros posicionales {"1": …}.
    La foto de la cabecera va aparte, con la clave «imagen»."""
    texto = _VARIABLE.sub(
        lambda m: str(valores[plantilla.variables[int(m.group(1)) - 1]]).strip(),
        plantilla.cuerpo,
    )
    parametros = {
        str(i): str(valores[rol]).strip() for i, rol in enumerate(plantilla.variables, 1)
    }
    if plantilla.encabezado == "IMAGE":
        parametros[ROL_IMAGEN] = str(valores[ROL_IMAGEN]).strip()
    return Escogida(grupo, plantilla, texto, parametros)


def roles_basicos(
    nombre: str | None = None, mascota: str | None = None, pieza: str | None = None
) -> dict[str, str]:
    """Lo que sale de la clienta y su pieza, con los respaldos de siempre:
    «de nuevo» si no se sabe su nombre, «tu peludito» si no se sabe el de su
    mascota. El resto (monto, saldo, código, fecha, guía…) cambia de sentido
    según la situación: lo pone quien manda."""
    return {
        "nombre": primer_nombre(nombre) if nombre else SIN_NOMBRE,
        "mascota": (mascota or "").strip() or "tu peludito",
        "pieza": {"cadena": "cadena", "corazon": "anillo de corazón"}.get(
            pieza or "", "anillo"
        ),
    }


def grupos_activos(ruta: Path) -> frozenset[str]:
    """Los grupos que Camilo prendió (`data/plantillas/activos.json`, una lista).
    Sin archivo o vacío: ninguno."""
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    return frozenset(str(g) for g in datos) if isinstance(datos, list) else frozenset()
