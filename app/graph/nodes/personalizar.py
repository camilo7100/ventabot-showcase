"""Nodo de personalización: lleva a la clienta por el diseño de su anillo.

CÓMO FUNCIONA, EN CUATRO LÍNEAS
===============================
1. Pregunta al guion qué se está esperando ahora mismo.
2. Interpreta el mensaje entrante COMO ESA RESPUESTA y nada más.
3. Guarda lo que entendió.
4. Vuelve a preguntar al guion qué sigue, y lo dice.

El paso 2 es la clave del determinismo. En vez de preguntarle al modelo "¿qué
quiso decir?" sobre un mensaje suelto, el sistema ya SABE qué preguntó, así
que solo tiene que leer una respuesta concreta. «morados» significa una cosa
muy distinta según si se preguntó por el corazón o por los deditos, y aquí
eso nunca es ambiguo.

Es también lo que permite que un modelo de 3B sea suficiente: nunca se le
pide que elija entre quince posibilidades, solo que lea un color de una lista
de catorce — y ni siquiera eso, porque los colores los lee Python
(`app.domain.colores_texto`) y el modelo solo interviene si Python no pudo.

QUÉ NO HACE ESTE NODO
=====================
No cobra, no crea pedidos y no cambia estados. Cuando el diseño queda
completo, muestra el resumen con el abono y deja que la clienta confirme;
de ahí en adelante manda `crear_pedido`, que es el que toca la plata.
Mantener separado "conversar" de "cobrar" es lo que hace que un error de
lectura nunca pueda convertirse en un cobro.

ANTE LA DUDA, PREGUNTA
======================
Ninguna rama de este archivo adivina. Si el color no se entiende, se vuelve a
preguntar mostrando lo que sí se leyó. Repreguntar cuesta un mensaje;
adivinar mal cuesta un anillo de plata fundido del color equivocado.
"""

from __future__ import annotations

import re

from app.domain.colores_texto import LecturaColores, leer_colores
from app.domain.faq import ENVIO_NACIONAL_COP, Pregunta, responder
from app.domain.guion import (
    IMAGENES,
    OPCIONES,
    Opcion,
    Paso,
    siguiente_paso,
    texto,
)
from app.domain.personalizacion import (
    MAX_GRABADOS,
    NOMBRE_COLOR,
    Huellita,
    Personalizacion,
)
from app.domain.pricing import cotizar, formatear_cop
from app.domain.tallas import medir
from app.graph.state import ConvState

#: "no", "ninguno", "sin grabado", "que vaya liso": no quiere grabado.
SIN_GRABADO = re.compile(
    r"\b(sin\s+grabado|ning[uú]n[oa]?|nada|no\s+quiero|liso|as[ií]\s+est[aá]\s+bien)\b",
    re.IGNORECASE,
)
#: "soy talla 7", "talla 8.5", "la 6". Acepta coma decimal, que es como se
#: escribe en Colombia.
TALLA = re.compile(r"\b(?:talla\s*)?(\d{1,2}(?:[.,]5)?)\b")

#: Separadores con los que la gente lista nombres: comas, "y", saltos.
SEPARADORES = re.compile(r"[,\n;]+|\s+y\s+|\s+&\s+", re.IGNORECASE)


def _personalizacion(state: ConvState) -> Personalizacion:
    return Personalizacion(**(state.get("diseno") or {}))


def _huellitas_esperadas(state: ConvState, products) -> int:
    """Cuántos pares de colores hay que pedir. 0 = aún no eligió producto."""
    guardado = state.get("huellitas_esperadas")
    if guardado:
        return int(guardado)

    sku = (state.get("entities") or {}).get("sku")
    if not sku:
        pedido = state.get("active_order") or {}
        items = pedido.get("items") or []
        sku = items[0].get("sku") if items else None
    if not sku:
        return 0

    producto = next((p for p in products.list_active() if p.sku == sku), None)
    return producto.huellitas if producto else 0


def _abono_pagado(state: ConvState) -> bool:
    return int((state.get("active_order") or {}).get("anticipo_pagado_cop") or 0) > 0


def _leer_nombres(texto_entrante: str) -> list[str]:
    partes = [p.strip(" .¡!¿?\"'") for p in SEPARADORES.split(texto_entrante or "")]
    # "que diga Luna" -> se cae "que diga". Se quitan las muletillas de una
    # sola palabra que nunca son nombres de mascota.
    basura = {
        "que",
        "diga",
        "digan",
        "porfa",
        "por",
        "favor",
        "el",
        "la",
        "nombre",
        "nombres",
        "seria",
        "sería",
        "es",
        "son",
        "quiero",
        "grabado",
        "con",
    }
    limpios = []
    for parte in partes:
        palabras = [w for w in parte.split() if w.lower() not in basura]
        if palabras:
            limpios.append(_como_nombre(" ".join(palabras)))
    return limpios[:MAX_GRABADOS]


def _como_nombre(texto_nombre: str) -> str:
    """«rocky» -> «Rocky». Se graba en plata: la mayúscula importa.

    Solo se toca si viene TODO en minúscula, que es como se escribe rápido en
    el celular. Si la clienta puso «MAX» o «McFly», se respeta tal cual: ella
    sabe cómo se escribe el nombre de su mascota mejor que nosotros.
    """
    if texto_nombre.islower():
        return " ".join(w.capitalize() for w in texto_nombre.split())
    return texto_nombre


def _motivo(exc: Exception) -> str:
    """La frase legible que hay dentro de un error de Pydantic.

    Pydantic envuelve el mensaje en tres líneas de contexto técnico. A la
    clienta le llega solo la frase que escribimos nosotros en el validador
    («no cabe en el aro», «tiene símbolos que el grabador no puede hacer»).
    """
    texto_error = str(exc)
    if "Value error, " in texto_error:
        texto_error = texto_error.split("Value error, ")[-1]
    return texto_error.splitlines()[0].strip()


def make_personalizar(products, orders):
    def personalizar(state: ConvState) -> dict:
        entrante = (state.get("inbound_text") or "").strip()
        ent = state.get("entities") or {}
        p = _personalizacion(state)
        esperadas = _huellitas_esperadas(state, products)
        pagado = _abono_pagado(state)

        # La guía de medición se responde siempre, esté donde esté la
        # conversación: es una duda, no una respuesta al paso actual.
        if ent.get("pregunta") == Pregunta.COMO_MEDIR_TALLA.value and p.talla is None:
            return _decir(
                state,
                p,
                esperadas,
                texto_libre=responder(Pregunta.COMO_MEDIR_TALLA),
                traza="guía de medición",
            )

        esperando = siguiente_paso(p, huellitas_esperadas=esperadas, abono_pagado=pagado)
        traza = [f"personalizar: esperando {esperando.value}"]

        # Sin mensaje que interpretar (se acaba de llegar a este paso, o la
        # clienta mandó una foto que no toca), no se intenta leer nada: se
        # hace la pregunta y ya. Sin este corte, entrar al paso de colores
        # con las manos vacías disparaba el "no te entendí" antes siquiera de
        # haber preguntado.
        if not entrante and not ent.get("diametro_mm"):
            return _decir(
                state, p, esperadas, traza="sin mensaje que leer", pagado=pagado
            )

        # ---- 2. Interpretar el mensaje COMO respuesta a `esperando` --------
        if esperando is Paso.COLORES:
            lectura = leer_colores(entrante)
            if lectura.completa:
                p = p.model_copy(
                    update={
                        "huellitas": [
                            *p.huellitas,
                            Huellita(corazon=lectura.corazon, dedos=lectura.dedos),
                        ]
                    }
                )
                traza.append(f"colores leídos: {p.huellitas[-1].describir()}")
            else:
                return _repreguntar_colores(state, p, esperadas, lectura, traza)

        elif esperando is Paso.GRABADO:
            if SIN_GRABADO.search(entrante):
                p = p.model_copy(update={"sin_grabado": True})
                traza.append("sin grabado")
            else:
                nombres = _leer_nombres(entrante)
                if not nombres:
                    return _decir(
                        state,
                        p,
                        esperadas,
                        texto_libre=texto(Paso.GRABADO),
                        opciones=OPCIONES.get(Paso.GRABADO),
                        traza="no se entendió el grabado, se repregunta",
                    )
                try:
                    # Se valida ANTES de asignar. `model_copy` no valida, así
                    # que asignar primero dejaba el nombre inválido metido en
                    # `p`, y ese `p` era el que se devolvía al estado: el
                    # emoji quedaba guardado justo en la rama que existe para
                    # rechazarlo.
                    candidato = Personalizacion.model_validate(
                        {**p.model_dump(), "grabados": nombres}
                    )
                except ValueError as exc:
                    # Un nombre con emoji o demasiado largo. Se le explica, en
                    # vez de fabricar algo que el grabador no puede hacer.
                    return _decir(
                        state,
                        p,
                        esperadas,
                        texto_libre=(
                            f"Ups, {_motivo(exc)}\n\n¿Me lo escribes de otra forma? 🙏"
                        ),
                        traza=f"grabado inválido: {exc}",
                    )
                p = candidato
                traza.append(f"grabado: {', '.join(nombres)}")

        elif esperando is Paso.TALLA:
            p, avance = _leer_talla(p, entrante, ent)
            traza.append(avance)
            if p.talla is not None and (pedido_id := _pedido_id(state)):
                # Aquí SÍ se persiste: el abono ya está pagado y perder la
                # talla ahora significaría llamar a la clienta a preguntarle.
                orders.guardar_personalizacion(pedido_id, p)
                traza.append("talla guardada en el pedido")

        # ---- 3. ¿Qué sigue? -----------------------------------------------
        return _decir(state, p, esperadas, traza=" · ".join(traza), pagado=pagado)

    # -- helpers, dentro del closure para no repetir dependencias -----------

    def _decir(
        state: ConvState,
        p: Personalizacion,
        esperadas: int,
        *,
        texto_libre: str | None = None,
        opciones: tuple[Opcion, ...] | None = None,
        traza: str = "",
        pagado: bool | None = None,
    ) -> dict:
        if pagado is None:
            pagado = _abono_pagado(state)
        paso = siguiente_paso(p, huellitas_esperadas=esperadas, abono_pagado=pagado)

        salida = {
            "diseno": p.model_dump(mode="json"),
            "huellitas_esperadas": esperadas,
            "paso": paso.value,
            "reply_kind": "guion",
            "reply_slots": {},
            "step": f"guion:{paso.value}",
            "trace": [traza] if traza else [],
        }

        if texto_libre is not None:
            salida["reply_text"] = texto_libre
            if opciones:
                salida["reply_options"] = [
                    {"id": o.id, "title": o.titulo, "description": o.descripcion}
                    for o in opciones
                ]
            return salida

        salida["reply_text"] = _texto_del_paso(state, p, esperadas, paso)
        if paso in OPCIONES:
            salida["reply_options"] = [
                {"id": o.id, "title": o.titulo, "description": o.descripcion}
                for o in OPCIONES[paso]
            ]
        if paso in IMAGENES:
            salida["reply_imagen"] = IMAGENES[paso]
        if paso is Paso.CONFIRMAR_Y_ABONAR:
            salida["reply_options"] = [
                {"id": "confirmar", "title": "Confirmar y abonar"},
                {"id": "cambiar", "title": "Cambiar el diseño"},
                {"id": "humano", "title": "Hablar con alguien"},
            ]
        return salida

    def _texto_del_paso(
        state: ConvState, p: Personalizacion, esperadas: int, paso: Paso
    ) -> str:
        if paso is Paso.COLORES:
            return texto(Paso.COLORES, numero=len(p.huellitas) + 1)
        if paso is Paso.GRABADO:
            return texto(Paso.GRABADO)
        if paso is Paso.CONFIRMAR_Y_ABONAR:
            return _texto_confirmacion(state, p)
        pedido = state.get("active_order") or {}
        if paso is Paso.TALLA:
            return texto(Paso.TALLA, codigo=pedido.get("codigo", "tu pedido"))
        if paso is Paso.LISTO:
            return texto(
                Paso.LISTO,
                nombre=((state.get("customer") or {}).get("nombre") or "").strip()
                or "😊",
                codigo=pedido.get("codigo", "tu pedido"),
                dias=10,
                dias_max=15,
            )
        return texto(Paso.ELEGIR_PRODUCTO)

    def _texto_confirmacion(state: ConvState, p: Personalizacion) -> str:
        """El mensaje donde se pide la plata. Los números los calcula Python."""
        pedido = state.get("active_order") or {}
        items = pedido.get("items") or []
        sku = items[0]["sku"] if items else (state.get("entities") or {}).get("sku")
        if not sku:
            # No debería llegarse aquí: para confirmar hace falta un producto.
            # Si pasa, se vuelve a la primera pregunta en vez de reventar.
            return texto(Paso.ELEGIR_PRODUCTO)
        catalogo = {x.sku: x for x in products.list_active()}
        cot = cotizar(
            catalogo, [(str(sku), 1)], envio_contraentrega_cop=ENVIO_NACIONAL_COP
        )
        s = cot.slots()
        return texto(
            Paso.CONFIRMAR_Y_ABONAR,
            resumen=p.describir(),
            total=formatear_cop(s["total"]),
            anticipo=formatear_cop(s["anticipo"]),
            saldo=formatear_cop(s["saldo"]),
            dias=s["dias"],
            dias_max=s["dias_max"],
            envio_contraentrega=formatear_cop(s["envio_contraentrega"]),
        )

    def _repreguntar_colores(
        state: ConvState,
        p: Personalizacion,
        esperadas: int,
        lectura: LecturaColores,
        traza: list[str],
    ) -> dict:
        """No se entendió. Se muestra lo que SÍ se leyó y se pregunta lo que falta."""
        numero = len(p.huellitas) + 1
        if lectura.sueltos:
            vistos = ", ".join(NOMBRE_COLOR[c] for c in lectura.sueltos)
            pista = (
                f"Vi que mencionaste *{vistos}* 😊 ¿Cuál va en el *corazón* "
                f"y cuál en los *deditos*?"
            )
        else:
            pista = (
                "No logré identificar el color 🙈 Escríbeme uno de los del "
                "muestrario, por ejemplo: «corazón lila y dedos morados»."
            )
        return _decir(
            state,
            p,
            esperadas,
            texto_libre=f"{pista}\n\n_Huellita {numero}_",
            traza=" · ".join([*traza, "colores no entendidos, se repregunta"]),
        )

    return personalizar


def _pedido_id(state: ConvState) -> str | None:
    return (state.get("active_order") or {}).get("id")


def _leer_talla(p: Personalizacion, entrante: str, ent: dict):
    """De un texto («soy talla 7») o de una foto ya medida por el nodo de visión."""
    # Caso foto: el modelo de visión dejó los milímetros en `entities`.
    mm = ent.get("diametro_mm")
    if mm:
        m = medir(float(mm), foto_clara=bool(ent.get("foto_clara", True)))
        p = p.model_copy(
            update={
                "talla": m.talla,
                "talla_revisar": m.revisar,
                "talla_motivo": m.motivo,
            }
        )
        return p, f"talla por foto: {m.etiqueta} (revisar={m.revisar})"

    encontrado = TALLA.search(entrante or "")
    if not encontrado:
        return p, "no se entendió la talla, se repregunta"
    valor = float(encontrado.group(1).replace(",", "."))
    try:
        # Validar ANTES de asignar, por lo mismo que el grabado: `model_copy`
        # no valida, y asignar primero deja el valor malo dentro del objeto
        # que se devuelve.
        validada = Personalizacion.model_validate({**p.model_dump(), "talla": valor})
    except ValueError:
        # Dijo un número que no es una talla ("la 25"). No se guarda: se
        # vuelve a preguntar. Fabricar una talla 25 es perder el anillo.
        return p, "talla fuera de rango, se repregunta"
    return validada, f"talla dicha por la clienta: {valor:g}"
