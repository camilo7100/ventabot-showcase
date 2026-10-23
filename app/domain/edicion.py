"""Lía edita los datos de un pedido a mano: desde el panel o desde Chatwoot.

Pedido de Camilo (29/09): todo lo OBLIGATORIO tiene que poder llenarlo Lía —la
dirección que la IA no entendió, la guía al despachar, la talla, los colores,
el grabado— y quedar igual en todos lados: el pedido, la memoria del bot y
Chatwoot. Lleno en uno, lleno en todos.

Esto es la parte pura: recibe los textos del formulario (o los atributos de
Chatwoot), valida y devuelve el pedido y el borrador nuevos más la lista de lo
que cambió. Guardar, avisar y sincronizar lo hace el contenedor.
"""

from __future__ import annotations

import re

from app.domain.asesora import Borrador, HuellitaDelBorrador
from app.domain.envio import DatosDeEnvio
from app.domain.models import Order
from app.domain.personalizacion import (
    ColorCircon,
    Huellita,
    Personalizacion,
    lados_de_la_cadena,
    texto_del_grabado,
)
from app.domain.tallas import leer_talla, talla_texto

#: Lo que se puede editar, con su nombre para las notas y el panel.
CAMPOS: dict[str, str] = {
    "talla": "talla",
    "grabado": "grabado",
    "sin_grabado": "sin grabado",
    "nombre_clienta": "nombre de la clienta",
    "destinatario": "a nombre de (guía)",
    "ciudad": "ciudad",
    "direccion": "dirección",
    "barrio": "barrio",
    "cedula": "cédula",
    "celular": "celular",
    "recoge": "lo recoge",
    "transportadora": "transportadora",
    "guia": "número de guía",
}

#: Los que también se editan desde Chatwoot (la ficha de la derecha). Los
#: colores no: son una lista por huellita y en Chatwoot son un texto.
DESDE_CHATWOOT = (
    "talla",
    "grabado",
    "destinatario",
    "ciudad",
    "direccion",
    "barrio",
    "cedula",
    "celular",
    "transportadora",
    "guia",
)


#: Lo del borrador que es de la clienta y de la guía, no de un anillo.
DE_LA_CLIENTA = (
    "nombre_clienta",
    "destinatario",
    "ciudad",
    "direccion",
    "barrio",
    "cedula",
    "celular",
    "recoge",
)


class EdicionInvalida(ValueError):
    """Lo que escribió no se puede guardar. El mensaje dice por qué."""


def separar_grabado(texto: str) -> list[str]:
    """«Luna ♡ Rocky», «Luna, Rocky» o uno por renglón -> ["Luna", "Rocky"]."""
    partes = re.split(r"\s*(?:♡|❤️?|,|\n|;)\s*", texto or "")
    return [" ".join(p.split()) for p in partes if p.strip()]


def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def aplicar_edicion(
    pedido: Order | None, borrador: Borrador | None, datos: dict[str, str]
) -> tuple[Order | None, Borrador, list[str]]:
    """Aplica lo que Lía escribió. Solo cambia lo que viene y es distinto.

    `datos` son textos, como llegan de un formulario: los vacíos NO borran
    (un campo en blanco en el panel es «no lo toqué»), salvo el grabado cuando
    se marca «sin grabado». Colores: `corazon_1`, `dedos_1`, `corazon_2`…
    Lanza `EdicionInvalida` si algo no se puede guardar (una talla que no
    existe, un grabado que no cabe).
    """
    todo = (borrador or Borrador()).model_copy(deep=True)
    # Con varios anillos (02/10) se edita uno: `anillo` = 1, 2… (sin él, el 1).
    total = max(len(pedido.items) if pedido else 0, todo.anillos_total, 1)
    try:
        indice = min(max(int(datos.get("anillo") or 1), 1), total) - 1
    except (TypeError, ValueError):
        indice = 0
    b = todo.vista(indice)
    item = pedido.items[indice] if pedido and indice < len(pedido.items) else None
    p = item.personalizacion if item and item.personalizacion else None
    envio = (pedido.envio if pedido and pedido.envio else None) or DatosDeEnvio()
    cambios: list[str] = []
    nuevo_p: dict = {}
    nuevo_envio: dict = {}

    def limpio(clave: str) -> str | None:
        valor = datos.get(clave)
        if valor is None:
            return None
        valor = " ".join(str(valor).split())
        return valor or None

    # -- el anillo ------------------------------------------------------------
    if (texto := limpio("talla")) is not None:
        talla = leer_talla(texto)
        if talla is None:
            raise EdicionInvalida(f"«{texto}» no es una talla (ej.: 7, 7½, 7.75)")
        try:
            Personalizacion(talla=talla)
        except ValueError as exc:
            raise EdicionInvalida(f"la talla {talla_texto(talla)} no existe") from exc
        actual = p.talla if p else b.talla
        if talla != actual or (p and p.talla_revisar) or not b.talla_confirmada:
            nuevo_p.update(
                talla=talla, talla_revisar=False, talla_motivo="Puesta por Lía"
            )
            b.talla, b.talla_revisar, b.talla_confirmada = talla, False, True
            b.talla_rango, b.talla_motivo = "", "Puesta por Lía"
            if talla != actual:
                cambios.append(f"talla: {talla_texto(talla)}")

    n = b.cantidad or (len(p.huellitas) if p else 0) or len(b.huellitas)
    huellitas = [
        HuellitaDelBorrador(corazon=h.corazon, dedos=h.dedos)
        for h in (p.huellitas if p else [])
    ] or [h.model_copy() for h in b.huellitas]
    while len(huellitas) < n:
        huellitas.append(HuellitaDelBorrador())
    colores_cambiaron = False
    for i in range(1, n + 1):
        for parte in ("corazon", "dedos"):
            valor = limpio(f"{parte}_{i}")
            if valor is None:
                continue
            try:
                color = ColorCircon(valor)
            except ValueError as exc:
                raise EdicionInvalida(f"«{valor}» no es un color del muestrario") from exc
            if getattr(huellitas[i - 1], parte) != color:
                setattr(huellitas[i - 1], parte, color)
                colores_cambiaron = True
    if colores_cambiaron:
        completas = [h for h in huellitas if h.completa]
        nuevo_p["huellitas"] = [
            Huellita(corazon=h.corazon, dedos=h.dedos) for h in completas if h.dedos
        ]
        b.huellitas = huellitas
        cambios.append("colores: " + " | ".join(h.describir() for h in completas))

    sin_grabado = str(datos.get("sin_grabado") or "").lower() in (
        "1",
        "true",
        "on",
        "si",
        "sí",
    )
    es_cadena = (p.pieza if p else b.pieza) == "cadena"
    if sin_grabado and es_cadena:
        raise EdicionInvalida("la cadena siempre lleva el nombre grabado")
    if sin_grabado:
        if (p and p.grabados) or b.grabado or not b.sin_grabado:
            nuevo_p.update(grabados=[], sin_grabado=True)
            b.grabado, b.sin_grabado = [], True
            cambios.append("sin grabado")
    elif (texto := limpio("grabado")) is not None:
        renglones = separar_grabado(datos.get("grabado") or "")
        if es_cadena:
            # La cadena: «lado 1 / lado 2», hasta 2 nombres por lado (03/10).
            lados = re.split(r"\s*(?:/|\n|\|)\s*", datos.get("grabado") or "")
            renglones, problemas = lados_de_la_cadena([x for x in lados if x.strip()])
            if not renglones:
                raise EdicionInvalida(problemas[0] if problemas else "falta el nombre")
        try:
            Personalizacion(grabados=renglones)
        except ValueError as exc:
            raise EdicionInvalida(f"el grabado no se puede: {exc}") from exc
        if renglones != (p.grabados if p else b.grabado):
            nuevo_p.update(grabados=renglones, sin_grabado=False)
            b.grabado, b.sin_grabado = renglones, False
            pieza = "cadena" if es_cadena else "anillo"
            cambios.append(f"grabado: {texto_del_grabado(renglones, pieza)}")

    # -- quién y a dónde --------------------------------------------------------
    if (texto := limpio("nombre_clienta")) is not None and texto != b.nombre_clienta:
        b.nombre_clienta = texto[:60]
        cambios.append(f"nombre: {texto}")
    if (texto := limpio("destinatario")) is not None and texto != (
        b.destinatario or envio.nombre
    ):
        b.destinatario = texto[:60]
        cambios.append(f"a nombre de: {texto}")
    for campo, maximo in (("ciudad", 60), ("direccion", 200), ("barrio", 80)):
        texto = limpio(campo)
        if texto is not None and texto != (getattr(b, campo) or getattr(envio, campo)):
            setattr(b, campo, texto[:maximo])
            cambios.append(f"{CAMPOS[campo]}: {texto}")
    for campo in ("cedula", "celular"):
        texto = limpio(campo)
        if texto is None:
            continue
        numero = _digitos(texto)
        if not 6 <= len(numero) <= 15:
            raise EdicionInvalida(f"«{texto}» no parece un número de {CAMPOS[campo]}")
        if numero != (getattr(b, campo) or getattr(envio, campo)):
            setattr(b, campo, numero)
            cambios.append(f"{CAMPOS[campo]}: {numero}")
    if "recoge" in datos:
        recoge = str(datos.get("recoge") or "").lower() in ("1", "true", "on", "si", "sí")
        if recoge != (b.recoge or envio.recoge):
            b.recoge = recoge
            cambios.append("lo recoge en la tienda" if recoge else "va por envío")
    for campo, maximo in (("transportadora", 40), ("guia", 40)):
        texto = limpio(campo)
        if texto is not None and texto != getattr(envio, campo):
            nuevo_envio[campo] = texto[:maximo]
            cambios.append(f"{CAMPOS[campo]}: {texto}")

    # Lo del anillo vuelve a SU anillo; lo de la clienta y la guía, al borrador.
    final = todo.model_copy(deep=True)
    for campo in DE_LA_CLIENTA:
        setattr(final, campo, getattr(b, campo))
    if indice < todo.anillos_total:
        # El bot sabe de este anillo (si no, es solo del pedido: Lía lo armó).
        final.poner_anillo(indice, b)
    if "talla" in nuevo_p and final.misma_talla and b.talla is not None:
        final.fijar_talla(indice, b.talla, b.talla_motivo)
    if total > 1:
        del_anillo = ("talla", "colores", "grabado", "sin grabado")
        cambios = [
            f"anillo {indice + 1}: {c}" if c.startswith(del_anillo) else c
            for c in cambios
        ]
    b = final

    if pedido is None:
        return None, b, cambios

    if nuevo_p and item is not None:
        base = p or Personalizacion()
        item = item.model_copy(
            update={"personalizacion": base.model_copy(update=nuevo_p)}
        )
    # «Todos de la misma talla»: la talla que pone Lía va a todos los anillos.
    todas_las_tallas = "talla" in nuevo_p and b.misma_talla
    datos_envio = {
        "nombre": (b.destinatario or b.nombre_clienta or envio.nombre)[:60],
        "ciudad": b.ciudad or envio.ciudad,
        "direccion": b.direccion or envio.direccion,
        "barrio": b.barrio or envio.barrio,
        "cedula": b.cedula or envio.cedula,
        "celular": b.celular or envio.celular,
        "recoge": b.recoge,
        **nuevo_envio,
    }
    nuevo_pedido = pedido.model_copy(
        update={
            "items": [
                item
                if k == indice and item is not None
                else _con_talla(i, nuevo_p)
                if todas_las_tallas
                else i
                for k, i in enumerate(pedido.items)
            ],
            "envio": envio.model_copy(update=datos_envio),
        }
    )
    return nuevo_pedido, b, cambios


def _con_talla(item, nuevo_p: dict):
    """La línea de otro anillo con la talla nueva (cuando todos son iguales)."""
    talla = {k: v for k, v in nuevo_p.items() if k.startswith("talla")}
    base = item.personalizacion or Personalizacion()
    return item.model_copy(update={"personalizacion": base.model_copy(update=talla)})
