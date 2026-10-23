"""El panel del taller: lo que Lía abre en el celular para trabajar.

POR QUÉ UNA PÁGINA Y NO UNA HOJA DE CÁLCULO
===========================================
Una hoja de cálculo compartida obliga a instalar algo, iniciar sesión, y deja
que cualquiera escriba cualquier cosa en cualquier celda — incluido un estado
que la máquina del pedido no permite. Esta página, en cambio:

  · se abre con un enlace, desde el celular, sin instalar nada
  · muestra los botones que la TABLA DE TRANSICIONES permite, y solo esos
  · deja el rastro de quién movió qué en el log de auditoría

Los botones no se esconden a mano: salen de `app.domain.operacion`, que los
saca de la misma tabla que usa el bot. Por eso desde «producción lista» no
existe el botón «despachar»: no existe la transición. La regla de negocio y
la pantalla no se pueden desincronizar porque son la misma fuente.

SEGURIDAD
=========
Aquí se ven nombres, teléfonos y montos de clientas reales, y el servidor se
publica por un túnel al internet abierto. Por eso:

  · si `PANEL_TOKEN` está vacío, el panel NO EXISTE (404). Encenderlo es una
    decisión explícita, no un descuido.
  · el token se compara con `compare_digest`, igual que la firma de Meta.
  · las páginas van con `noindex` y sin `Referer`, para que el enlace no se
    filtre a Google ni a los sitios que se abran desde aquí.

El token viaja en la URL para que Lía pueda guardar el enlace como acceso
directo en su pantalla de inicio. Es un compromiso consciente: una contraseña
en la URL se queda en el historial del navegador. Para el tamaño de este
negocio es el equilibrio correcto entre seguridad y que ella lo use de
verdad; el día que haya varias personas operando, esto pasa a ser un login.
"""

from __future__ import annotations

import contextlib
import hmac
import html
import logging
import pathlib
import re
from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from app.adapters.almacen_fotos import AlmacenDeFotos, FotoInvalida
from app.domain.atencion import minutos_restantes
from app.domain.models import (
    Channel,
    OutboundMessage,
    conversation_id,
    new_id,
)
from app.domain.operacion import (
    DIAS_PARA_ALERTAR,
    PedidoIncompleto,
    SinFotosDelAnillo,
    acciones_de,
    avisa_este_estado,
    bandejas,
    dias_esperando,
    falta_para_despachar,
    falta_para_taller,
    talla_dudosa,
)
from app.domain.order_state import ETIQUETA_CLIENTE, OrderState, TransicionInvalida
from app.domain.ports import ConflictoDeEstado
from app.domain.pricing import formatear_cop
from app.domain.tallas import leer_talla, talla_texto, tallas_validas
from app.infra.container import get_container

log = logging.getLogger("ventabot.panel")

#: Las horas se muestran como las vive Lía, no en UTC. Se pone el desfase a
#: mano —igual que en el Excel de ventas— porque Windows no trae la base de
#: zonas horarias y `ZoneInfo("America/Bogota")` revienta ahí.
HORA_COLOMBIA = timezone(timedelta(hours=-5), "America/Bogota")
_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES_LARGOS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _fecha_larga(momento: datetime) -> str:
    """«jueves 01 de octubre, 21:37»: en español aunque el servidor esté en inglés
    (el %A de strftime salía «Thursday … October», 01/10)."""
    return (
        f"{_DIAS[momento.weekday()]} {momento:%d} de {_MESES_LARGOS[momento.month - 1]}, "
        f"{momento:%H:%M}"
    )


router = APIRouter(prefix="/panel", tags=["panel"])


def _exigir_token(token: str) -> None:
    c = get_container()
    esperado = c.settings.panel_token
    if not esperado:
        # 404 y no 403: si el panel está apagado, lo correcto es que no exista.
        # Un 403 le confirma a quien sondea que aquí hay algo que abrir.
        raise HTTPException(status_code=404, detail="not found")
    # En BYTES. Con dos `str`, `compare_digest` solo admite ASCII y con
    # cualquier otra cosa —un «…», una «ñ»— no dice «no cuadra»: revienta con
    # un 500. Pasó el 20/09 con un enlace mal copiado, y como todo el panel
    # pasa por esta puerta, se caían el taller, las charlas y todo lo demás.
    if not hmac.compare_digest((token or "").encode("utf-8"), esperado.encode("utf-8")):
        # SIN token no es un intento de entrar: es alguien que abrió /panel a
        # secas (Camilo sin el enlace, un rastreador, o el propio `vb
        # diagnostico`, que comprueba en cada arranque que esto esté cerrado).
        # Avisar de eso llena la ventana del servidor de alarmas falsas, y una
        # alarma que suena siempre deja de ser una alarma.
        #
        # CON un token que no cuadra sí: eso es alguien probando llaves.
        if token:
            log.warning("intento de entrar al panel con un token que no cuadra")
        else:
            log.debug("alguien abrió /panel sin el enlace completo")
        raise HTTPException(status_code=404, detail="not found")


def _medio_del_mensaje(mensaje: dict) -> str:
    """La foto o el video de un mensaje, listo para meter en la burbuja.

    Antes en el panel una foto era la palabra «[image]» y Lía no podía ver el
    prototipo que el bot le acababa de mandar a la clienta (Camilo, 20/09).

    Las URL son las mismas que ve WhatsApp —públicas y con nombre imposible de
    adivinar—, así que el navegador las carga sin más.
    """
    import json

    crudo = mensaje.get("payload")
    if not crudo:
        return ""
    try:
        datos = json.loads(crudo)
    except (TypeError, ValueError):
        return ""
    url = (datos.get("media_url") or "").strip()
    # Solo nuestras URL: nunca lo que venga escrito en un mensaje de fuera.
    if not url.startswith(("http://", "https://")) or (
        "/media/" not in url and "/panel/foto/" not in url
    ):
        return ""
    seguro = html.escape(url, quote=True)
    if datos.get("kind") == "video":
        return f"<video src='{seguro}' controls preload=metadata class=medio></video>"
    return f"<img src='{seguro}' alt='' loading=lazy class=medio>"


def _sin_texto(mensaje: dict) -> str:
    """Qué era un mensaje sin texto: «📷 Foto», «🎤 Nota de voz», «Reaccionó ❤️…».

    Las fotos y audios de la clienta no se ven aquí (viven en Meta, con token):
    se ven en Chatwoot. Aquí al menos se sabe qué mandó, y no «[adjunto]».
    """
    import json

    from app.adapters.channels.whatsapp import detalle_sin_archivo
    from app.domain.models import etiqueta_de_adjunto

    try:
        datos = json.loads(mensaje.get("payload") or "{}")
    except (TypeError, ValueError):
        datos = {}
    tipo = datos.get("type") or datos.get("kind") or ""
    if not tipo:
        return "[adjunto]"
    cuerpo = datos.get(tipo) if isinstance(datos.get(tipo), dict) else {}
    return etiqueta_de_adjunto(
        tipo, detalle_sin_archivo(tipo, datos), (cuerpo or {}).get("filename") or ""
    )


def _almacen() -> AlmacenDeFotos:
    return AlmacenDeFotos(get_container().settings.fotos_dir)


def _huellitas_por_sku() -> dict[str, int]:
    return {p.sku: p.huellitas for p in get_container().products.list_active()}


# ---------------------------------------------------------------------------
# HTML. Sin framework de plantillas y sin CDN: una sola página, que carga en
# un celular con mala señal en el taller. Todo el CSS va aquí dentro.
# ---------------------------------------------------------------------------

ESTILO = """
:root{--fondo:#faf7f5;--tarjeta:#fff;--borde:#ecdfd8;--texto:#2c2422;
--suave:#8a7a74;--acento:#c96f8b;--alerta:#b8562f;--ok:#3f7d5a}
*{box-sizing:border-box}
body{margin:0;font:16px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif;
background:var(--fondo);color:var(--texto)}
header{background:var(--tarjeta);border-bottom:1px solid var(--borde);
padding:14px 16px;position:sticky;top:0;z-index:5}
h1{margin:0;font-size:17px;letter-spacing:.02em}
.sub{color:var(--suave);font-size:13px;margin-top:2px}
main{padding:12px 12px 48px;max-width:760px;margin:0 auto}
section{margin:22px 0}
h2{font-size:15px;margin:0 0 2px;display:flex;align-items:center;gap:8px}
.cuenta{background:var(--acento);color:#fff;border-radius:999px;
padding:1px 9px;font-size:12px;font-weight:600}
.ayuda{color:var(--suave);font-size:13px;margin:0 0 10px}
.vacio{color:var(--suave);font-size:14px;font-style:italic;padding:6px 0}
article{background:var(--tarjeta);border:1px solid var(--borde);
border-radius:12px;padding:13px 14px;margin-bottom:10px}
article.urgente{border-color:var(--alerta);border-width:2px}
.fila{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.codigo{font-weight:700;letter-spacing:.03em}
.dias{color:var(--suave);font-size:12px;white-space:nowrap}
.dias.tarde{color:var(--alerta);font-weight:600}
.estado{color:var(--suave);font-size:13px;margin:3px 0 8px}
.dato{font-size:14px;margin:2px 0}
.envio{background:#f4f7f4;border-left:3px solid #7aa77a;
padding:8px 10px;border-radius:6px;margin:8px 0}
.aviso{background:#fdf1ec;border-left:3px solid var(--alerta);
padding:8px 10px;border-radius:6px;margin:8px 0;font-size:14px}
.aviso ul{margin:6px 0 0;padding-left:18px}
.aviso li{margin:3px 0}
.falta{background:#fff8e6;border-left:3px solid #c99a2e;
padding:8px 10px;border-radius:6px;margin:8px 0;font-size:14px}
.plata{font-size:14px;color:var(--suave);margin-top:6px}
.botones{display:flex;flex-wrap:wrap;gap:8px;margin-top:11px}
button{font:inherit;font-size:14px;padding:9px 14px;border-radius:9px;
border:1px solid var(--borde);background:#fff;color:var(--texto);cursor:pointer}
button.principal{background:var(--acento);border-color:var(--acento);color:#fff;
font-weight:600}
button.peligro{color:var(--alerta);border-color:#e8c4b6}
form{display:inline}
form.mover,form.talla{display:block}
.campo input{display:block;width:100%;font:inherit;font-size:15px;padding:8px 10px;
border-radius:9px;border:1px solid var(--borde);margin-top:3px;color:var(--texto);
background:#fff}
.pareja{display:flex;gap:6px}
.casilla{display:block;margin:8px 0 0;font-size:14px}
details.escribir{margin-top:10px;font-size:14px}
details.escribir summary{cursor:pointer;color:var(--suave)}
.campo{display:block;margin:8px 0 0;font-size:13px;color:var(--suave)}
.campo textarea,.campo select{display:block;width:100%;font:inherit;font-size:15px;
padding:8px 10px;border-radius:9px;border:1px solid var(--borde);margin-top:3px;
color:var(--texto);background:#fff;resize:vertical}
.fotos{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 0}
.fotos img{width:74px;height:74px;object-fit:cover;border-radius:8px;
border:1px solid var(--borde)}
.subir{margin-top:10px}
.subir input[type=file]{display:none}
.subir label{display:inline-block;font-size:14px;padding:9px 14px;
border-radius:9px;border:1px dashed var(--borde);color:var(--suave);
cursor:pointer;background:#fff}
.subir label:hover{border-color:var(--acento);color:var(--acento)}
.medio{display:block;max-width:100%;width:230px;border-radius:9px;
margin:0 0 6px;background:#f2ecea}
.chat{display:flex;flex-direction:column;gap:7px;margin:12px 0}
.burbuja{max-width:82%;padding:9px 12px;border-radius:13px;font-size:15px;
line-height:1.4;word-wrap:break-word}
.burbuja.suyo{align-self:flex-start;background:#fff;border:1px solid var(--borde)}
.burbuja.mio{align-self:flex-end;background:#e7f0ff}
.burbuja .hora{display:block;font-size:11px;color:var(--suave);margin-top:4px}
.responder{display:flex;flex-direction:column;gap:8px}
.responder textarea{font:inherit;font-size:15px;padding:10px;border-radius:10px;
border:1px solid var(--borde);width:100%;box-sizing:border-box;resize:vertical}
article a{text-decoration:none;color:inherit;display:block}
.mando{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
gap:9px;margin:10px 0 0}
.chip{background:var(--tarjeta);border:1px solid var(--borde);border-radius:11px;
padding:10px 12px}
.chip.mal{border-color:var(--alerta);border-width:2px}
.chip .que{color:var(--suave);font-size:12px;text-transform:uppercase;
letter-spacing:.04em}
.chip .como{font-size:15px;font-weight:600;margin-top:3px}
.chip .detalle{color:var(--suave);font-size:12px;margin-top:2px}
.enlaces{display:grid;gap:9px;margin-top:10px}
.enlaces a{display:block;background:var(--tarjeta);border:1px solid var(--borde);
border-radius:11px;padding:12px 14px;text-decoration:none;color:inherit}
.enlaces a:hover{border-color:var(--acento)}
.enlaces .titulo{font-size:15px;font-weight:600}
.enlaces .para{color:var(--suave);font-size:13px;margin-top:2px}
.ruta{font-family:ui-monospace,Consolas,monospace;font-size:12px;
background:#f4f1f0;border:1px solid var(--borde);border-radius:7px;
padding:7px 9px;margin-top:8px;word-break:break-all;color:var(--suave)}
pre.registro{background:#1e1b1a;color:#e8e3e0;border-radius:10px;padding:12px;
font-size:12px;line-height:1.5;overflow-x:auto;white-space:pre-wrap;
word-break:break-word}
"""


def _cabecera(titulo: str) -> str:
    return (
        "<!doctype html><html lang=es><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<meta name=robots content='noindex,nofollow'>"
        "<meta name=referrer content='no-referrer'>"
        f"<title>{html.escape(titulo)}</title><style>{ESTILO}</style></head><body>"
    )


def _ventana_abierta(pedido) -> bool:
    """Si WhatsApp todavía deja escribirle texto libre a esta clienta.

    Meta solo permite mensajes libres dentro de las 24 h siguientes al último
    mensaje de la clienta. Pasado eso, exige una PLANTILLA aprobada por ellos.
    Como la fabricación son 10-15 días, esto se cierra en casi todos los
    pedidos: es la regla, no la excepción.
    """
    c = get_container()
    cliente = c.customers.get(pedido.customer_id)
    if cliente is None or c.conversaciones is None:
        return False
    return c.conversaciones.ventana_abierta(
        conversation_id(cliente.channel, cliente.channel_user_id)
    )


def _por_confirmar(pedido) -> list[str]:
    """Lo que el bot detectó y una persona tiene que verificar.

    ════════════════════════════════════════════════════════════════════════
    POR QUÉ ESTO ESTÁ AQUÍ Y NO EN EL CHAT
    ════════════════════════════════════════════════════════════════════════
    El bot no se bloquea ante la duda: si el lector de imágenes no está
    seguro de una talla o de un color, guarda lo que vio, lo apunta y sigue
    conversando. Esa política solo funciona si lo apuntado LLEGA A ALGUIEN.

    Un aviso que nadie mira es lo mismo que no avisar, y este es el sitio
    donde se mira: cuelga del pedido, junto a los botones que lo mueven, y no
    en un log que nadie abre.
    """
    c = get_container()
    cliente = c.customers.get(pedido.customer_id)
    if cliente is None or c.contexto is None:
        return []
    ctx = c.contexto.cargar(conversation_id(cliente.channel, cliente.channel_user_id))
    return list(ctx.revisar)


def _tarjeta(pedido, token: str, huellitas: dict[str, int]) -> str:
    dias = dias_esperando(pedido)
    tarde = dias >= DIAS_PARA_ALERTAR
    estado = OrderState(pedido.estado)
    item = pedido.items[0] if pedido.items else None
    p = item.personalizacion if item else None

    clase_dias = "tarde" if tarde else ""
    prefijo_dias = "sin moverse " if tarde else ""
    clase_articulo = "urgente" if talla_dudosa(pedido) else ""

    partes = [
        f"<article class='{clase_articulo}'>",
        "<div class=fila>",
        f"<span class=codigo>{html.escape(pedido.codigo)}</span>",
        f"<span class='dias {clase_dias}'>{prefijo_dias}hace {dias} d</span>",
        "</div>",
        f"<div class=estado>{html.escape(ETIQUETA_CLIENTE[estado])}</div>",
    ]
    if estado is OrderState.EN_REVISION_PAGO:
        # Qué comprobante es: sin esto, un saldo en revisión parecía un abono
        # (28/09). El botón de abajo confirma justo este.
        if pedido.anticipo_pagado_cop:
            debe = pedido.saldo_cop - pedido.saldo_pagado_cop
            que = f"el <b>SALDO</b> de {formatear_cop(debe)}"
        else:
            que = f"el <b>ABONO</b> de {formatear_cop(pedido.anticipo_cop)}"
        partes.append(
            f"<div class=aviso>💰 Mandó el comprobante: verifica {que} en el banco "
            "y confírmalo con el botón de abajo.</div>"
        )

    varios = len(pedido.items) > 1
    for k, it in enumerate(pedido.items, 1):
        # Varios anillos en un pedido (02/10): cada uno con su título.
        cadena = it.personalizacion is not None and it.personalizacion.pieza == "cadena"
        if not varios:
            titulo = ""
        elif cadena:
            titulo = f"📿 Pieza {k} de {len(pedido.items)} · "
        else:
            titulo = f"💍 Anillo {k} de {len(pedido.items)} · "
        partes.append(f"<div class=dato>{html.escape(titulo + it.nombre)}</div>")
        if it.personalizacion and (texto := it.personalizacion.describir()):
            for linea in texto.splitlines():
                partes.append(f"<div class=dato>{html.escape(linea)}</div>")

    # A dónde va. Sin esto hay que abrir el WhatsApp para despachar, y es
    # justo cuando más prisa hay.
    if pedido.envio and (destino := pedido.envio.describir()):
        partes.append("<div class=envio>")
        for linea in destino.splitlines():
            partes.append(f"<div class=dato>{html.escape(linea)}</div>")
        partes.append("</div>")

    for k, it in enumerate(pedido.items, 1):
        q = it.personalizacion
        if q and q.talla_revisar:
            cual = f" del anillo {k}" if varios else ""
            partes.append(
                f"<div class=aviso><b>Confirma la talla{cual}.</b> "
                f"{html.escape(q.talla_motivo)}</div>"
            )

    if not _ventana_abierta(pedido):
        partes.append(
            "<div class=falta><b>WhatsApp no deja escribirle ahora.</b> "
            "Pasaron más de 24 h desde su último mensaje. El aviso queda "
            "encolado y sale solo en cuanto ella escriba. Si tienes prisa, "
            "escríbele tú primero desde el celular.</div>"
        )

    if notas := _por_confirmar(pedido):
        partes.append("<div class=aviso><b>Confirma antes de fabricar:</b><ul>")
        for nota in notas:
            partes.append(f"<li>{html.escape(nota)}</li>")
        partes.append("</ul></div>")

    if faltan := falta_para_taller(pedido, huellitas_por_sku=huellitas):
        partes.append(
            f"<div class=falta>Falta por preguntarle: "
            f"{html.escape(', '.join(faltan))}</div>"
        )

    # Lo que la clienta debe se calcula por DIFERENCIA, igual que el saldo:
    # total menos lo que efectivamente entró. Nunca a partir de porcentajes.
    debe = pedido.total_cop - pedido.anticipo_pagado_cop - pedido.saldo_pagado_cop
    partes.append(
        f"<div class=plata>Total {formatear_cop(pedido.total_cop)} · "
        f"abonado {formatear_cop(pedido.anticipo_pagado_cop)} · "
        f"debe {formatear_cop(debe)}</div>"
    )

    # Las fotos del anillo terminado. Son lo que convierte el cobro del saldo
    # en la entrega de algo que ella reconoce.
    if pedido.fotos:
        partes.append("<div class=fotos>")
        for nombre in pedido.fotos:
            url = f"/panel/foto/{html.escape(nombre)}"
            partes.append(f"<img src='{url}' alt='foto del anillo' loading=lazy>")
        partes.append("</div>")

    partes.append(
        f"<div class=subir>"
        f"<form method=post enctype='multipart/form-data' "
        f"action='/panel/fotos?token={html.escape(token)}'>"
        f"<input type=hidden name=pedido_id value='{html.escape(pedido.id)}'>"
        f"<label>📷 Agregar fotos del anillo"
        f"<input type=file name=archivos accept='image/*' multiple "
        f"onchange='this.form.submit()'>"
        f"</label></form></div>"
    )

    if varios:
        for k, it in enumerate(pedido.items, 1):
            # La cadena no lleva talla (03/10).
            if it.personalizacion is not None and it.personalizacion.pieza != "cadena":
                partes.append(
                    _talla_de_la_tarjeta(pedido, it.personalizacion, token, anillo=k)
                )
        for k, it in enumerate(pedido.items, 1):
            partes.append(_datos_del_pedido(pedido, it.personalizacion, token, anillo=k))
        partes.append(_datos_del_pedido(pedido, None, token, anillo=-1))
    else:
        if p is not None and p.pieza != "cadena":
            partes.append(_talla_de_la_tarjeta(pedido, p, token))
        partes.append(_datos_del_pedido(pedido, p, token))

    acciones = acciones_de(pedido)
    if acciones:
        # UN formulario para todos los botones del pedido, con los dos textos
        # opcionales (27/09): lo que se le dice a la clienta y la nota interna.
        # Cada botón manda su `destino`; los textos van con el que se toque.
        partes.append(
            f"<form method=post class=mover "
            f"action='/panel/mover?token={html.escape(token)}'>"
            f"<input type=hidden name=pedido_id value='{html.escape(pedido.id)}'>"
            + _guia_para_despachar(pedido, acciones)
            + _DOS_TEXTOS
            + "<div class=botones>"
        )
        for i, accion in enumerate(acciones):
            clase = "peligro" if accion.peligro else ("principal" if i == 0 else "")
            escribe = avisa_este_estado(accion.destino)
            # Un botón que a veces le escribe a la clienta y a veces no, sin
            # decir cuál es cuál, se usa con miedo. El sobrecito lo dice.
            etiqueta = f"✉ {accion.titulo}" if escribe else accion.titulo
            partes.append(
                f"<button class='{clase}' name=destino value='{accion.destino.value}' "
                f'onclick="{_confirmar_mover(accion.peligro, escribe)}">'
                f"{html.escape(etiqueta)}</button>"
            )
        partes.append("</div></form>")
    partes.append("</article>")
    return "".join(partes)


def _guia_para_despachar(pedido, acciones) -> str:
    """La guía, obligatoria, junto al botón «Despachado» (Camilo, 29/09)."""
    if not any(a.destino is OrderState.DESPACHADO for a in acciones):
        return ""
    envio = pedido.envio
    if envio is not None and envio.recoge:
        return ""
    transportadora = html.escape(
        (envio.transportadora if envio else "") or "Coordinadora"
    )
    guia = html.escape(envio.guia if envio else "")
    return (
        "<div class=envio><b>🚚 Para despacharlo</b> · la guía es obligatoria y le "
        "llega a ella en el mensaje."
        "<label class=campo>Transportadora"
        f"<input name=transportadora value='{transportadora}' maxlength=40></label>"
        "<label class=campo>Número de guía"
        f"<input name=guia value='{guia}' maxlength=40 placeholder='Ej.: 700012345678'>"
        "</label></div>"
    )


def _datos_del_pedido(pedido, p, token: str, anillo: int = 0) -> str:
    """Todo lo obligatorio, editable a mano (Camilo, 29/09).

    `anillo`: 0 = todo en un formulario (un pedido de un anillo); con varios
    anillos (02/10), 1, 2… = solo lo de ese anillo, y -1 = solo la guía.

    Lo que Lía guarda aquí queda igual en el pedido, en la memoria del bot y en
    la ficha de Chatwoot. Un campo vacío es «no lo toqué»: no borra nada.
    """
    from app.domain.asesora import unir_grabado
    from app.domain.personalizacion import NOMBRE_COLOR, ColorCircon

    envio = pedido.envio
    faltan = falta_para_despachar(pedido) if envio is not None else []

    def campo(nombre: str, etiqueta: str, valor: str, largo: int = 80, ayuda="") -> str:
        extra = f" placeholder='{html.escape(ayuda)}'" if ayuda else ""
        return (
            f"<label class=campo>{html.escape(etiqueta)}"
            f"<input name={nombre} value='{html.escape(valor or '')}' "
            f"maxlength={largo}{extra}></label>"
        )

    def colores(nombre: str, actual) -> str:
        opciones = ["<option value=''>—</option>"] + [
            f"<option value='{c.value}'{' selected' if actual == c else ''}>"
            f"{html.escape(NOMBRE_COLOR[c].capitalize())}</option>"
            for c in ColorCircon
        ]
        return f"<select name={nombre}>{''.join(opciones)}</select>"

    titulo = {0: "Datos del pedido", -1: "Datos de la guía"}.get(
        anillo, f"Anillo {anillo}"
    )
    del_anillo, de_la_guia = anillo >= 0, anillo <= 0
    partes = [
        f"<details class=escribir><summary>✏️ {titulo} (corregir o completar)"
        + (
            f" · <b>falta: {html.escape(', '.join(faltan))}</b>"
            if de_la_guia
            and faltan
            and OrderState(pedido.estado) is not OrderState.EN_PRODUCCION
            else ""
        )
        + "</summary>",
        "<form method=post class=talla "
        f"action='/panel/datos?token={html.escape(token)}'>",
        f"<input type=hidden name=pedido_id value='{html.escape(pedido.id)}'>",
        f"<input type=hidden name=anillo value={anillo}>" if anillo > 0 else "",
        "<input type=hidden name=recoge_presente value=1>" if de_la_guia else "",
        "<p class=ayuda>Lo que guardes aquí queda igual en el pedido, en el bot y "
        "en Chatwoot. Un campo vacío no borra nada.</p>",
    ]
    if del_anillo:
        partes += _campos_del_anillo(p, campo, colores, unir_grabado)
    if de_la_guia:
        partes += _campos_de_la_guia(envio, campo)
    partes += [
        "<div class=botones><button class=principal>Guardar cambios</button></div>",
        "</form></details>",
    ]
    return "".join(partes)


def _campos_del_anillo(p, campo, colores, unir_grabado) -> list[str]:
    partes = []
    huellitas = p.huellitas if p else []
    for i, h in enumerate(huellitas or [None], 1):
        partes.append(
            f"<label class=campo>Huellita {i}: corazón / deditos"
            f"<span class=pareja>{colores(f'corazon_{i}', h.corazon if h else None)}"
            f"{colores(f'dedos_{i}', h.dedos if h else None)}</span></label>"
        )
    if p is not None and p.pieza == "cadena":
        # La cadena (03/10): un lado / el otro, hasta 2 nombres por lado, siempre.
        partes.append(
            campo(
                "grabado",
                "Grabado por lado: lado 1 / lado 2 (hasta 2 nombres por lado)",
                " / ".join(p.grabados),
                120,
            )
        )
        return partes
    partes.append(
        campo(
            "grabado",
            "Grabado (separa los nombres con ♡ o coma)",
            unir_grabado(p.grabados) if p and p.grabados else "",
            120,
        )
    )
    marcado = " checked" if p and p.sin_grabado else ""
    partes.append(
        f"<label class=casilla><input type=checkbox name=sin_grabado value=1{marcado}> "
        "Va sin grabado</label>"
    )
    return partes


def _campos_de_la_guia(envio, campo) -> list[str]:
    partes = [
        campo(
            "destinatario",
            "A nombre de (para la guía)",
            envio.nombre if envio else "",
            60,
        ),
        campo("ciudad", "Ciudad", envio.ciudad if envio else "", 60),
        campo(
            "direccion",
            "Dirección completa",
            envio.direccion if envio else "",
            200,
            "Calle, número, torre/apto",
        ),
        campo("barrio", "Barrio", envio.barrio if envio else "", 80),
        campo("cedula", "Cédula", envio.cedula if envio else "", 15),
        campo("celular", "Celular para la guía", envio.celular if envio else "", 15),
    ]
    recoge = " checked" if envio and envio.recoge else ""
    partes.append(
        f"<label class=casilla><input type=checkbox name=recoge value=1{recoge}> "
        "Lo recoge en la tienda (no necesita dirección ni guía)</label>"
    )
    partes += [
        campo(
            "transportadora",
            "Transportadora",
            (envio.transportadora if envio else "") or "Coordinadora",
            40,
        ),
        campo("guia", "Número de guía", envio.guia if envio else "", 40),
    ]
    return partes


#: Los dos textos opcionales de cada movimiento (27/09). Plegados: casi nunca
#: hacen falta, y la tarjeta tiene que seguir leyéndose de un vistazo.
_DOS_TEXTOS = (
    "<details class=escribir><summary>✍️ Agregar mensaje o nota (opcional)</summary>"
    "<label class=campo>Mensaje para la clienta · <b>le llega por WhatsApp</b>"
    "<textarea name=mensaje rows=2 maxlength=1500></textarea></label>"
    "<label class=campo>Nota interna · <b>ella no la ve</b> (queda en Chatwoot y el "
    "bot la tiene en cuenta)"
    "<textarea name=nota rows=2 maxlength=1000></textarea></label>"
    "</details>"
)


def _confirmar_mover(peligro: bool, escribe: bool) -> str:
    """El `onclick` de un botón: qué preguntar antes de mover.

    Si Lía escribió un mensaje, siempre se pregunta, porque va a salir ya. Va
    dentro del botón y no en un <script>: el panel no lleva ninguno, y así
    un <script> en la página siempre es señal de algo mal escapado.
    """
    if peligro:
        base = "¿Seguro? Esto no se deshace."
    elif escribe:
        base = "Esto le escribe a la clienta ahora mismo. ¿Lo mando?"
    else:
        base = ""
    con_mensaje = (base + " " if peligro else "") + (
        "Tu mensaje le llega a la clienta ahora mismo. ¿Lo mando?"
    )
    return (
        "var m=this.form.elements.mensaje.value.trim();"
        f"var p=m?'{con_mensaje}':'{base}';"
        "return p?confirm(p):true"
    )


def _talla_de_la_tarjeta(pedido, p, token: str, anillo: int = 0) -> str:
    """Confirmar o corregir la talla, con su nota y su mensaje (27/09).

    La talla que calculó la IA de una medida es una REFERENCIA: la
    conversación no esperó por Lía y el pedido llegó al abono igual. Aquí Lía
    la confirma o la corrige, y desde ahí es la talla que vale. Abierto si
    está por confirmar; plegado si no.
    """
    actual = p.talla
    opciones = [] if actual is not None else ["<option value='' selected>—</option>"]
    for t in tallas_validas():
        marcada = " selected" if actual is not None and t == actual else ""
        opciones.append(f"<option value='{t:g}'{marcada}>{talla_texto(t)}</option>")
    if actual is None:
        estado = "sin talla"
    elif p.talla_revisar:
        estado = "por confirmar"
    elif (p.talla_motivo or "").startswith(("Confirmada", "Corregida")):
        estado = "confirmada ✓"
    else:
        estado = "la dijo ella"
    abierta = " open" if p.talla_revisar or actual is None else ""
    return (
        f"<details class=escribir{abierta}><summary>📏 Talla"
        + (f" del anillo {anillo}" if anillo else "")
        + " "
        f"{html.escape(talla_texto(actual) or '—')} · {html.escape(estado)}</summary>"
        f"<form method=post class=talla action='/panel/talla?token={html.escape(token)}' "
        'onsubmit="var m=this.elements.mensaje.value.trim();return m?confirm('
        "'Tu mensaje le llega a la clienta ahora mismo. ¿Lo mando?'):true\">"
        f"<input type=hidden name=pedido_id value='{html.escape(pedido.id)}'>"
        + (f"<input type=hidden name=anillo value={anillo}>" if anillo else "")
        + f"<label class=campo>Talla<select name=talla required>{''.join(opciones)}"
        "</select></label>"
        "<label class=campo>Nota interna · <b>ella no la ve</b>"
        "<textarea name=nota rows=2 maxlength=1000 placeholder='Ej.: Es la que mejor "
        "corresponde con la foto enviada.'></textarea></label>"
        "<label class=campo>Mensaje para la clienta (opcional) · <b>le llega por "
        "WhatsApp</b><textarea name=mensaje rows=2 maxlength=1500></textarea></label>"
        "<div class=botones><button class=principal>Guardar talla</button></div>"
        "</form></details>"
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def ver_panel(token: str = "") -> HTMLResponse:
    _exigir_token(token)
    c = get_container()
    pedidos = c.orders.abiertos()
    huellitas = _huellitas_por_sku()

    cuerpo = [
        _cabecera("Taller · Luna Joyas"),
        "<header><h1>Taller</h1>",
        f"<div class=sub>{len(pedidos)} pedidos en curso · "
        f"<a href='/panel/chats?token={html.escape(token)}'>conversaciones</a> · "
        f"<a href='/panel/metricas?token={html.escape(token)}'>métricas</a> · "
        f"<a href='/panel/marketing?token={html.escape(token)}'>"
        "<b>📣 marketing</b></a> · "
        f"<a href='/panel/finanzas?token={html.escape(token)}'>"
        "<b>💰 finanzas</b></a> · "
        f"<a href='/panel/todo?token={html.escape(token)}'>todo</a> · "
        f"<a href='/panel/flujo?token={html.escape(token)}'>el flujo</a> · "
        f"<a href='/panel/instructivo?token={html.escape(token)}'>"
        "<b>📖 instructivo</b></a> · "
        f"<a href='/panel/envios?token={html.escape(token)}'>envíos</a> · "
        f"<a href='/panel/colores?token={html.escape(token)}'>colores</a> · "
        f"<a href='/panel/datos.csv?token={html.escape(token)}'>datos (Excel)</a>"
        "</div></header><main>",
    ]
    cuerpo.append(_tallas_por_confirmar(c, token))

    for bandeja in bandejas(pedidos):
        cuerpo.append("<section>")
        cuenta = f"<span class=cuenta>{bandeja.cuantos}</span>" if bandeja.cuantos else ""
        cuerpo.append(f"<h2>{html.escape(bandeja.titulo)}{cuenta}</h2>")
        cuerpo.append(f"<p class=ayuda>{html.escape(bandeja.ayuda)}</p>")
        if not bandeja.pedidos:
            cuerpo.append("<div class=vacio>Nada pendiente aquí ✨</div>")
        for pedido in bandeja.pedidos:
            cuerpo.append(_tarjeta(pedido, token, huellitas))
        cuerpo.append("</section>")

    cuerpo.append("</main></body></html>")
    return HTMLResponse("".join(cuerpo))


def _tallas_por_confirmar(c, token: str) -> str:
    """Regla de Lía (29/09): la talla la confirma ella, antes del abono.

    Todavía no hay pedido (nace al pedir el abono), así que aquí salen las
    CONVERSACIONES que mandaron la foto de la regla o una medida. Lía ve la
    foto, lo que sugiere la IA y lo que falta; escoge la talla y confirma. A la
    clienta le llega su talla y, si ya estaba todo, el resumen para el abono.
    """
    from app.domain.asesora import TALLA_DE_LIA, Borrador

    if not c.settings.talla_la_confirma_lia or not hasattr(c.contexto, "recientes"):
        return ""
    pendientes = []
    for ctx in c.contexto.recientes(200):
        if not ctx.borrador:
            continue
        b = Borrador.model_validate(ctx.borrador)
        b.talla_exige_lia = True
        if b.talla_por_confirmar and not b.pedido_id:
            pendientes.append((ctx.conversation_id, b))

    cuenta = f"<span class=cuenta>{len(pendientes)}</span>" if pendientes else ""
    partes = [
        "<section>",
        f"<h2>📏 Tallas por confirmar{cuenta}</h2>",
        "<p class=ayuda>Mandaron la foto de la regla o la medida. El bot no les "
        "dijo ninguna talla: les dijo que en unos minutos se la confirmas, y siguió "
        "con los colores. El abono espera tu confirmación.</p>",
    ]
    if not pendientes:
        partes.append("<div class=vacio>Nada pendiente aquí ✨</div>")
    for conv, b in pendientes:
        partes.append(_tarjeta_de_talla(c, conv, b, token, TALLA_DE_LIA))
    partes.append("</section>")
    return "".join(partes)


def _tarjeta_de_talla(c, conv: str, b, token: str, talla_de_lia: str) -> str:
    quien = b.nombre_clienta or ""
    if not quien:
        cliente = c.bot._mundo.cliente_de(conv) if hasattr(c.bot, "_mundo") else None
        quien = (getattr(cliente, "nombre", "") or "") if cliente else ""
    faltan = [f for f in b.falta_para_abono() if f != talla_de_lia]
    # Varios anillos (02/10): las fotos y la sugerencia son las del anillo que
    # espera la talla, y se dice cuál es.
    cual = ""
    if b.varios or b.anillos:
        pendiente = b.pendiente_de_talla()
        indice = len(b.anillos) if pendiente is None else pendiente
        cual = (
            f"Anillos {b.anillos_total} (todos de la misma talla)"
            if b.misma_talla
            else f"Anillo {indice + 1} de {b.anillos_total}"
        )
        b = b.vista(indice)
    partes = [
        "<article class=urgente>",
        "<div class=fila>",
        f"<span class=codigo>{html.escape(quien or _bonito(conv))}</span>",
        f"<a class=dias href='/panel/chat?conv={html.escape(conv)}"
        f"&token={html.escape(token)}'>ver el chat →</a>",
        "</div>",
        f"<div class=estado>{html.escape(_bonito(conv))}</div>",
    ]
    if cual:
        partes.append(f"<div class=dato><b>💍 {html.escape(cual)}</b></div>")
    if b.talla_fotos:
        partes.append("<div class=fotos>")
        for nombre in b.talla_fotos:
            url = f"/panel/foto/{html.escape(nombre)}"
            partes.append(
                f"<a href='{url}' target=_blank rel=noopener>"
                f"<img src='{url}' alt='foto de la regla' loading=lazy></a>"
            )
        partes.append("</div><div class=ayuda>Toca la foto para verla grande.</div>")
    if b.talla_escrita:
        partes.append(
            "<div class=dato>Escribió la medida: "
            f"<b>«{html.escape(b.talla_escrita)}»</b></div>"
        )
    if b.talla is not None and b.talla_revisar:
        rango = f" ({html.escape(b.talla_rango)})" if b.talla_rango else ""
        partes.append(
            f"<div class=dato>La IA sugiere: <b>{html.escape(talla_texto(b.talla))}</b>"
            f"{rango} · es solo una sugerencia</div>"
        )
    elif b.talla is not None:
        partes.append(
            f"<div class=dato>Ella dijo que es talla "
            f"<b>{html.escape(talla_texto(b.talla))}</b></div>"
        )
    else:
        partes.append("<div class=dato>La IA no alcanzó a leer la medida.</div>")
    if faltan:
        partes.append(
            "<div class=falta>Además le falta escoger: "
            f"{html.escape(', '.join(faltan))} (el bot se lo sigue preguntando).</div>"
        )
    else:
        partes.append(
            "<div class=envio><b>Ya escogió todo.</b> Apenas confirmes, le llega su "
            "talla y el resumen para que diga que sí y pague el abono.</div>"
        )
    opciones = [] if b.talla is not None else ["<option value='' selected>—</option>"]
    for talla in tallas_validas():
        marcada = " selected" if b.talla is not None and talla == b.talla else ""
        opciones.append(
            f"<option value='{talla:g}'{marcada}>{talla_texto(talla)}</option>"
        )
    partes.append(
        "<form method=post class=talla "
        f"action='/panel/talla-charla?token={html.escape(token)}' "
        'onsubmit="var m=this.elements.mensaje.value.trim();return confirm(m?'
        "'Le llega tu mensaje ahora mismo. ¿Lo mando?':"
        "'Le llega: ¡Listo! Ya revisé tu medida: tu talla es la que escogiste. "
        "¿Lo mando?')\">"
        f"<input type=hidden name=conv value='{html.escape(conv)}'>"
        f"<label class=campo>Talla<select name=talla required>{''.join(opciones)}"
        "</select></label>"
        "<label class=campo>Nota interna · <b>ella no la ve</b>"
        "<textarea name=nota rows=2 maxlength=1000 placeholder='Ej.: Es la que mejor "
        "corresponde con la foto enviada.'></textarea></label>"
        "<label class=campo>Mensaje para la clienta (opcional) · si lo dejas vacío le "
        "llega «¡Listo! 💍 Ya revisé tu medida: tu talla es la …»"
        "<textarea name=mensaje rows=2 maxlength=1500></textarea></label>"
        "<div class=botones><button class=principal>Confirmar talla ✓</button></div>"
        "</form></article>"
    )
    return "".join(partes)


def _chip(que: str, como: str, detalle: str = "", bien: bool = True) -> str:
    clase = "chip" if bien else "chip mal"
    extra = f"<div class=detalle>{html.escape(detalle)}</div>" if detalle else ""
    return (
        f"<div class='{clase}'><div class=que>{html.escape(que)}</div>"
        f"<div class=como>{html.escape(como)}</div>{extra}</div>"
    )


def _qr(texto: str) -> str:
    """El enlace como código QR, dibujado aquí mismo en SVG.

    Se genera en el servidor con `segno`: el enlace lleva la llave del panel y
    no sale hacia ningún servicio de QR de internet. Si la librería faltara,
    la página sigue igual sin el dibujo — el enlace para copiar está debajo.
    """
    try:
        import io

        import segno
    except ImportError:
        return ""
    salida = io.BytesIO()
    segno.make(texto, error="m").save(
        salida, kind="svg", scale=5, border=2, xmldecl=False, svgns=True
    )
    return (
        "<div style='background:#fff;display:inline-block;padding:6px;"
        "border-radius:10px;border:1px solid var(--borde)'>"
        + salida.getvalue().decode("utf-8")
        + "</div>"
    )


def _enlace(url: str, titulo: str, para: str, fuera: bool = False) -> str:
    destino = " target=_blank rel=noopener" if fuera else ""
    return (
        f"<a href='{html.escape(url, quote=True)}'{destino}>"
        f"<div class=titulo>{html.escape(titulo)}</div>"
        f"<div class=para>{html.escape(para)}</div></a>"
    )


def _hace_cuanto(cuando) -> str:
    """«hace 3 h 12 min». Lo único que se quiere saber de una marca de tiempo."""
    if cuando is None:
        return "—"
    from datetime import datetime

    if isinstance(cuando, int | float):
        cuando = datetime.fromtimestamp(cuando, tz=UTC)
    segundos = int((datetime.now(UTC) - cuando).total_seconds())
    if segundos < 60:
        return "hace un momento"
    if segundos < 3600:
        return f"hace {segundos // 60} min"
    if segundos < 86400:
        return f"hace {segundos // 3600} h {(segundos % 3600) // 60} min"
    return f"hace {segundos // 86400} día(s)"


@router.get("/flujo", response_class=HTMLResponse)
def ver_flujo(token: str = "") -> HTMLResponse:
    """Cómo vende el bot, con cada mensaje preestablecido (ver `app.api.flujo`)."""
    from app.api.flujo import pagina

    _exigir_token(token)
    return HTMLResponse(pagina(get_container(), token, _cabecera))


@router.get("/instructivo", response_class=HTMLResponse)
def ver_instructivo(token: str = "", doc: str = "camilo") -> HTMLResponse:
    """El instructivo de Camilo, el manual de Lía y cómo está hecho (05/10)."""
    from app.api.instructivo import pagina

    _exigir_token(token)
    return HTMLResponse(pagina(token, doc, _cabecera))


@router.get("/marketing", response_class=HTMLResponse)
def ver_marketing(
    token: str = "",
    vista: str = "hoy",
    anio: str = "",
    mes: str = "",
    campana: str = "",
    fase: str = "",
    por: str = "",
    plan: str = "",
) -> HTMLResponse:
    """El marketing, por pestañas (ver `app.api.marketing`).

    Además de la carpeta de marketing le pasa lo que sabe el bot (sus pedidos)
    y la última foto del ERP (01/10). En «Piloto» (03/10), también el embudo
    del chat día por día (`tablero.embudo_por_dia`, desde que las ventas son
    de verdad) y los filtros de esa pestaña.
    """
    import json

    from app.api.marketing import pagina

    _exigir_token(token)
    c = get_container()
    s = c.settings
    bot_filas = None
    if getattr(c, "analitica", None) is not None:
        try:
            c.refrescar_analitica()
            bot_filas = c.analitica.filas()
        except Exception as exc:  # el marketing se ve igual sin esto
            log.warning("panel: sin pedidos para el marketing (%s)", exc)
    foto = None
    with contextlib.suppress(OSError, ValueError):
        foto = json.loads(s.marketing_foto_del_erp.read_text(encoding="utf-8"))
    embudo = None
    if vista == "piloto":
        from app.adapters.repositories.tablero import embudo_por_dia

        try:
            embudo = embudo_por_dia(c.db, s.ventas_reales_desde.strip() or "0000-00-00")
        except Exception as exc:  # la pestaña se ve igual, sin lo del chat
            log.warning("panel: sin el embudo del chat para el piloto (%s)", exc)
    return HTMLResponse(
        pagina(
            s.marketing_dir,
            token,
            _cabecera,
            vista,
            bot_filas=bot_filas,
            reales_desde=s.ventas_reales_desde,
            foto_erp=foto,
            anio=anio,
            mes=mes,
            embudo_bot=embudo,
            piloto={"campana": campana, "fase": fase, "por": por, "plan": plan},
        )
    )


@router.post("/marketing/erp")
def actualizar_marketing_del_erp(token: str = ""):
    """Botón «Actualizar del ERP»: pauta → Publicidad, ciudades y foto (01/10)."""
    from app.adapters.erp.marketing import actualizar
    from app.adapters.erp.sheets import SheetsDeGoogle

    _exigir_token(token)
    s = get_container().settings
    if s.sheets_spreadsheet_id and s.google_service_account_json:
        try:
            hoja = SheetsDeGoogle(s.sheets_spreadsheet_id, s.google_service_account_json)
            campanas = s.marketing_dir / "datos" / "meta_campanas_mensual.csv"
            texto = campanas.read_text(encoding="utf-8-sig") if campanas.is_file() else ""
            log.info(
                "panel: ERP ← marketing: %s",
                actualizar(hoja, texto, s.marketing_foto_del_erp),
            )
        except Exception as exc:
            log.warning("panel: no se pudo actualizar el ERP (%s)", exc)
    return RedirectResponse(
        f"/panel/marketing?token={token}&vista=numeros#erp", status_code=303
    )


@router.get("/finanzas", response_class=HTMLResponse)
def ver_finanzas(
    token: str = "", vista: str = "resumen", anio: str = "", mes: str = ""
) -> HTMLResponse:
    """Las finanzas del ERP por pestañas (ver `app.api.finanzas`, 01/10)."""
    import json

    from app.api.finanzas import pagina

    _exigir_token(token)
    s = get_container().settings
    foto = None
    with contextlib.suppress(OSError, ValueError):
        foto = json.loads(s.finanzas_foto_del_erp.read_text(encoding="utf-8"))
    return HTMLResponse(pagina(foto, token, _cabecera, vista, anio, mes))


@router.post("/finanzas/erp")
def actualizar_finanzas_del_erp(token: str = "", vista: str = "resumen"):
    """Botón «Actualizar del ERP» de las finanzas: lee el ERP y guarda la foto."""
    from app.adapters.erp.finanzas import guardar
    from app.adapters.erp.sheets import SheetsDeGoogle

    _exigir_token(token)
    s = get_container().settings
    if s.sheets_spreadsheet_id and s.google_service_account_json:
        try:
            hoja = SheetsDeGoogle(s.sheets_spreadsheet_id, s.google_service_account_json)
            guardar(hoja, s.finanzas_foto_del_erp)
        except Exception as exc:
            log.warning("panel: no se pudo leer el ERP para finanzas (%s)", exc)
    vista = vista if vista.isalpha() else "resumen"
    return RedirectResponse(
        f"/panel/finanzas?token={token}&vista={vista}", status_code=303
    )


@router.get("/todo", response_class=HTMLResponse)
def ver_centro_de_mando(token: str = "") -> HTMLResponse:
    """Todo lo que controla el negocio, en una página y a un clic.

    Antes había que acordarse de seis direcciones: el taller, las charlas,
    Chatwoot, el ERP, el registro y la base. Esto es la portada de las seis,
    con el estado de cada una en vivo para no tener que abrirlas para saber si
    están bien (Camilo, 20/09).
    """
    _exigir_token(token)
    import sqlite3
    from datetime import datetime

    c = get_container()
    s = c.settings
    t = html.escape(token, quote=True)

    # -- el estado de cada pieza -------------------------------------------
    chips = []
    from app.infra.container import ARRANCADO as arranque

    chips.append(_chip("El bot", "atendiendo", _hace_cuanto(arranque)))

    pendientes = 0
    with contextlib.suppress(Exception):
        pendientes = c.outbox.pendientes()
    chips.append(
        _chip(
            "Por enviar",
            "nada en cola" if not pendientes else f"{pendientes} mensaje(s)",
            "si se atasca, mira el registro" if pendientes else "",
            bien=pendientes < 5,
        )
    )

    cifras, peso = "—", ""
    with contextlib.suppress(Exception):
        ruta = s.sqlite_path
        peso = f"{ruta.stat().st_size // 1024} KB"
        con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        # Las consultas son literales —no viene nada de fuera— pero se
        # escriben enteras para que se lea de un vistazo que es así.
        n = {
            "orders": con.execute("select count(*) from orders").fetchone()[0],
            "conversations": con.execute("select count(*) from conversations").fetchone()[
                0
            ],
        }
        con.close()
        cifras = f"{n['orders']} pedidos · {n['conversations']} charlas"
    chips.append(_chip("La base", cifras, peso))

    erp = getattr(getattr(c, "erp", None), "ultimo", None)
    chips.append(
        _chip(
            "El ERP",
            "al día" if erp is not None else "sin sincronizar aún",
            str(erp) if erp is not None else "se pone al día cada 10 min",
            bien=erp is not None,
        )
    )

    copia, cuando_copia = "sin copias", ""
    with contextlib.suppress(Exception):
        carpeta = (
            pathlib.Path.home() / "Documents" / "Respaldos" / "VentaBot" / "automatico"
        )
        ultimas = sorted(carpeta.glob("ventabot-*.db"), key=lambda p: p.stat().st_mtime)
        if ultimas:
            copia = ultimas[-1].name
            cuando_copia = _hace_cuanto(ultimas[-1].stat().st_mtime)
    chips.append(
        _chip("Última copia", cuando_copia or copia, copia if cuando_copia else "")
    )

    revisar = 0
    with contextlib.suppress(Exception):
        revisar = sum(1 for p in c.orders.abiertos() if _por_confirmar(p))
    chips.append(
        _chip(
            "Por revisar",
            "nada pendiente" if not revisar else f"{revisar} pedido(s)",
            "el taller te los marca" if revisar else "",
            bien=not revisar,
        )
    )

    publico = (s.url_publica_override or s.public_url or "").rstrip("/")
    cuerpo = [
        _cabecera("Centro de mando · Luna Joyas"),
        "<header><h1>Centro de mando</h1>",
        f"<div class=sub>{_fecha_larga(datetime.now(HORA_COLOMBIA))}"
        "</div></header><main>",
        "<section><h2>Cómo va todo ahora</h2>",
        f"<div class=mando>{''.join(chips)}</div></section>",
        "<section><h2>Para atender</h2><div class=enlaces>",
        _enlace(
            f"/panel?token={t}",
            "El taller 🔨",
            "Los pedidos en curso con sus botones, las tallas por confirmar y los "
            "pagos por verificar",
        ),
        _enlace(
            f"/panel/chats?token={t}",
            "Las conversaciones 💬",
            "Leer y contestarle a una clienta sin salir de aquí",
        ),
        _enlace(
            (s.chatwoot_url_publica or publico or s.chatwoot_url or "").rstrip("/"),
            "Chatwoot 🗂️",
            "El CRM completo: etiquetas, notas, carpetas y la app del celular",
            fuera=True,
        ),
        "</div></section>",
        "<section><h2>Para saber cómo va el negocio</h2><div class=enlaces>",
        _enlace(
            f"/panel/finanzas?token={t}",
            "Las finanzas 💰",
            "Lo vendido, la utilidad mes a mes, la caja, cuánto cuesta de verdad cada "
            "pieza (capa por capa), los materiales y qué se vende: todo del ERP",
        ),
        "</div></section>",
        "<section><h2>Para vender más</h2><div class=enlaces>",
        _enlace(
            f"/panel/marketing?token={t}",
            "El marketing 📣",
            "Qué hacer con la pauta de Instagram, los números del mes, las campañas, "
            "los videos, la estrategia y toda la carpeta de marketing",
        ),
        "</div></section>",
        "<section><h2>Para entender y ajustar</h2><div class=enlaces>",
        _enlace(
            f"/panel/flujo?token={t}",
            "El flujo del bot 🗺️",
            "Cada mensaje que sale, en orden y con su código; los datos obligatorios "
            "y qué pasa en cada caso",
        ),
        _enlace(
            f"/panel/instructivo?token={t}",
            "El instructivo 📖",
            "Todo documentado: tu instructivo, el manual de atención de Lía y cómo "
            "está hecho el sistema, con buscador y por secciones",
        ),
        _enlace(
            f"/panel/envios?token={t}",
            "Los envíos 🚚",
            "Cuánto cuesta el envío, a todo el país o por ciudad",
        ),
        _enlace(
            f"/panel/colores?token={t}",
            "Los colores 💎",
            "El nombre y el color de cada bolsita de circones (corazón y deditos)",
        ),
        "</div></section>",
        "<section><h2>Para controlar</h2><div class=enlaces>",
        _enlace(
            f"/panel/metricas?token={t}",
            "Las métricas 📊",
            "Capas de IA, escaladas, costo y latencia de cada turno",
        ),
        _enlace(
            f"/panel/datos.csv?token={t}",
            "Los datos de todos los pedidos 📑",
            "Un Excel con una fila por pedido y cada dato en su columna, para analizar",
        ),
        _enlace(
            f"https://docs.google.com/spreadsheets/d/{s.sheets_spreadsheet_id}/edit",
            "El ERP · HUELLAS_ERP_v1 📒",
            "Ventas (la sábana real y lo del bot), costos capa por capa, balance, "
            "gráficas y el tablero",
            fuera=True,
        ),
        _enlace(
            f"/panel/registro?token={t}",
            "El registro del servidor 📜",
            "Lo último que hizo el bot, sin abrir ninguna ventana negra",
        ),
        "</div>",
        "</section>",
    ]

    if publico:
        # El enlace ENTERO. Antes iba con «…» en lugar del token para no
        # enseñarlo, y al copiarlo así tumbaba el panel (20/09). Enseñarlo aquí
        # no descubre nada: para ver esta página ya está en la barra de arriba.
        para_el_celular = f"{publico}/panel/todo?token={token}"
        cuerpo += [
            "<section><h2>Desde el celular</h2>",
            "<p class=ayuda>Escanea el código con la cámara del teléfono, o "
            "copia el enlace. Guárdalo en la pantalla de inicio y lo tienes de "
            "una. Lleva la llave del panel: no lo mandes a ningún grupo.</p>",
            _qr(para_el_celular),
            f"<div class=ruta id=enlace>{html.escape(para_el_celular)}</div>",
            "<div class=botones><button class=principal type=button "
            'onclick="navigator.clipboard.writeText('
            "document.getElementById('enlace').textContent)"
            ".then(()=>{this.textContent='¡Copiado! ✓'})\">"
            "Copiar el enlace</button></div></section>",
        ]

    cuerpo.append("</main></body></html>")
    return HTMLResponse("".join(cuerpo))


@router.get("/registro", response_class=HTMLResponse)
def ver_registro(token: str = "", lineas: int = 120) -> HTMLResponse:
    """Lo último del registro, para no tener que abrir la ventana del servidor.

    Camilo lo pidió tal cual: «no quiero estarte copiando y pegando». Se leen
    los últimos bytes, no el archivo entero: después de una noche pesa megas.
    """
    _exigir_token(token)
    c = get_container()
    archivo = pathlib.Path("logs") / "servidor.log"
    if not archivo.is_file():
        archivo = c.settings.sqlite_path.parent.parent / "logs" / "servidor.log"
    try:
        crudo = archivo.read_bytes()[-120_000:].decode("utf-8", errors="replace")
        cola = crudo.splitlines()[-max(20, min(lineas, 500)) :]
    except Exception as exc:
        cola = [f"no se pudo leer el registro ({exc})"]

    # Por si algún día algo escribe una clave: aquí se ve en una pantalla que
    # puede estar abierta delante de cualquiera.
    secretos = [
        v
        for v in (
            c.settings.panel_token,
            getattr(c.settings, "anthropic_api_key", ""),
            getattr(c.settings, "wa_access_token", ""),
            getattr(c.settings, "chatwoot_token", ""),
        )
        if v and len(str(v)) > 8
    ]
    texto = "\n".join(cola)
    for secreto in secretos:
        texto = texto.replace(str(secreto), "•••")

    return HTMLResponse(
        "".join(
            [
                _cabecera("Registro · Luna Joyas"),
                "<header><h1>El registro</h1>",
                f"<div class=sub>lo último que hizo el bot · "
                f"<a href='/panel/todo?token={html.escape(token, quote=True)}'>"
                "volver</a></div></header><main>",
                f"<pre class=registro>{html.escape(texto)}</pre>",
                "</main></body></html>",
            ]
        )
    )


def _aviso(
    titulo: str, que_paso: str, que_hacer: str, token: str, *, extra: str = "", status=409
) -> HTMLResponse:
    """La página de «no se hizo, por esto, y así se arregla».

    Las reglas del panel están bien (no cobrar sin fotos, no fundir sin talla,
    no despachar sin dirección); lo que no estaba bien era cómo se decían: una
    pantalla de «Internal Server Error» o un `{"detail": …}` (Camilo, 28/09).
    Todas las restricciones pasan por aquí y se leen igual.
    """
    return HTMLResponse(
        _cabecera(titulo) + f"<main><section><article><h3>{html.escape(titulo)}</h3>"
        f"<p>{que_paso}</p><p class=ayuda>{que_hacer}</p>{extra}"
        f"<a href='/panel?token={html.escape(token)}'>← volver al taller</a>"
        "</article></section></main></body></html>",
        status_code=status,
    )


#: Qué se estaba intentando, para el título de un pedido incompleto.
_PARA_QUE = {
    OrderState.EN_PRODUCCION: "No puede entrar al taller todavía",
    OrderState.DESPACHADO: "No se puede despachar todavía",
}


@router.post("/mover")
def mover(
    request: Request,
    token: str = "",
    pedido_id: str = Form(...),
    destino: str = Form(...),
    mensaje: str = Form(""),
    nota: str = Form(""),
    guia: str = Form(""),
    transportadora: str = Form(""),
):
    """Mueve un pedido. La validación real la hace el dominio, no esta función.

    Aquí no se comprueba si la transición es legal: eso lo decide
    `transicionar()`, que consulta la tabla. Duplicar la regla en la web sería
    la forma de que un día las dos versiones digan cosas distintas. Lo que sí
    se hace aquí es DECIR por qué no se movió (`_aviso`).
    """
    _exigir_token(token)
    c = get_container()
    pedido = c.orders.get(pedido_id)
    guardado = _no_salio(mensaje, nota)
    if pedido is None:
        return _aviso(
            "No encontré ese pedido",
            "Ese pedido ya no existe (se borró, o era de una prueba que se reinició).",
            "Vuelve al taller: la página se actualiza con los pedidos de ahora.",
            token,
            extra=guardado,
            status=404,
        )
    try:
        estado = OrderState(destino)
    except ValueError:
        return _aviso(
            "Ese botón no es válido",
            "El botón mandó un estado que el sistema no conoce.",
            "Recarga el taller y vuelve a tocarlo. Si se repite, avísale a Camilo.",
            token,
            extra=guardado,
            status=400,
        )

    # El pedido YA está donde se lo quiere llevar: el dedo resbaló, o la
    # página se recargó, o Lía le dio dos veces porque el celular iba lento.
    # Eso no es un error que merezca una pantalla roja: es un no-op.
    #
    # Se comprueba aquí y no en `transicionar()` a propósito. Para el dominio,
    # ESPERANDO_SALDO -> ESPERANDO_SALDO sí es una transición inválida y debe
    # seguir siéndolo: es lo que impide que un webhook duplicado avance el
    # pedido dos veces. Lo que cambia es qué hace la INTERFAZ con ese caso.
    if OrderState(pedido.estado) is estado:
        log.info("panel: %s ya estaba en %s, no se hace nada", pedido.codigo, destino)
        return RedirectResponse(f"/panel?token={token}", status_code=303)

    # Todo lo que pasa al mover (la regla del 100 %, la transición, los montos
    # pagados, el aviso a la clienta con sus fotos, la memoria del bot, Chatwoot
    # y el ERP) vive en UN sitio: `Container.mover_pedido`. El aviso va por la
    # outbox, así que si WhatsApp está caído se reintenta y no se pierde.
    codigo = html.escape(pedido.codigo)
    try:
        c.mover_pedido(
            pedido,
            estado,
            actor="panel",
            motivo="movido desde el panel del taller",
            mensaje=mensaje,
            nota=nota,
            guia=guia,
            transportadora=transportadora,
        )
    except PedidoIncompleto as exc:
        solo_la_guia = exc.faltan == ["número de guía"]
        return _aviso(
            _PARA_QUE.get(estado, "Falta información"),
            f"Al pedido {codigo} le falta: <b>{html.escape(', '.join(exc.faltan))}</b>.",
            (
                "Escribe el número de guía en el recuadro 🚚 que está junto al botón "
                "«Despachado» y vuelve a tocarlo."
                if solo_la_guia
                else "Pídeselo a la clienta, o escríbelo tú en <b>✏️ Datos del "
                "pedido</b>, y vuelve a intentar."
            )
            + " No se le mandó nada a la clienta.",
            token,
            extra=guardado,
        )
    except SinFotosDelAnillo:
        # 28/09: salía «Internal Server Error». La regla es buena —«ya está
        # listo» sin fotos es cobrar por algo que ella no ha visto—, pero hay
        # que decir qué hacer, igual que cuando falta un dato.
        return _aviso(
            "Primero las fotos del anillo",
            f"El pedido {codigo} todavía no tiene fotos del anillo terminado, y el "
            "cobro del saldo se las manda a la clienta: sin fotos se le estaría "
            "cobrando algo que no ha visto.",
            "En la tarjeta del pedido toca <b>📷 Agregar fotos del anillo</b>, escoge "
            "las fotos y vuelve a tocar <b>Cobrar el saldo</b>. No se le mandó nada "
            "a la clienta.",
            token,
            extra=guardado,
        )
    except (TransicionInvalida, ConflictoDeEstado):
        # La página estaba vieja: alguien lo movió desde otro celular, desde
        # Chatwoot, o el bot lo movió al llegar un comprobante.
        ahora = c.orders.get(pedido.id)
        donde = (
            ETIQUETA_CLIENTE.get(OrderState(ahora.estado), ahora.estado) if ahora else ""
        )
        return _aviso(
            "Ese pedido ya cambió",
            f"El pedido {codigo} ya no está donde lo veías"
            + (f": ahora está en «{html.escape(donde)}»." if donde else ".")
            + " Alguien lo movió mientras tenías la página abierta (otro "
            "celular, Chatwoot o el bot).",
            "Vuelve al taller para verlo como está ahora y, si hace falta, toca el "
            "botón que corresponda. No se le mandó nada a la clienta.",
            token,
            extra=guardado,
        )
    log.info("panel: %s -> %s", pedido.codigo, estado.value)
    # 303 para que recargar la página no vuelva a mover el pedido.
    return RedirectResponse(f"/panel?token={token}", status_code=303)


def _no_salio(mensaje: str, nota: str) -> str:
    """Si el pedido no se movió, lo que Lía escribió no se pierde: se le
    muestra para que lo copie y lo vuelva a pegar."""
    partes = []
    if (mensaje or "").strip():
        partes.append(
            "<p class=ayuda>Tu mensaje para la clienta <b>no se mandó</b>. "
            f"Cópialo para la próxima:</p><pre class=ruta>{html.escape(mensaje)}</pre>"
        )
    if (nota or "").strip():
        partes.append(
            "<p class=ayuda>Tu nota interna tampoco se guardó:</p>"
            f"<pre class=ruta>{html.escape(nota)}</pre>"
        )
    return "".join(partes)


@router.post("/talla")
def confirmar_talla(
    token: str = "",
    pedido_id: str = Form(...),
    talla: str = Form(...),
    nota: str = Form(""),
    mensaje: str = Form(""),
    anillo: int = Form(0),
):
    """Lía confirma o corrige la talla (27/09). Desde ahí es la que vale.

    `anillo` (1, 2…) en un pedido de varios anillos (02/10)."""
    _exigir_token(token)
    c = get_container()
    pedido = c.orders.get(pedido_id)
    guardado = _no_salio(mensaje, nota)
    if pedido is None:
        return _aviso(
            "No encontré ese pedido",
            "Ese pedido ya no existe (se borró, o era de una prueba que se reinició).",
            "Vuelve al taller: la página se actualiza con los pedidos de ahora.",
            token,
            extra=guardado,
            status=404,
        )
    valor = leer_talla(talla)
    try:
        if valor is None:
            raise ValueError(talla)
        c.confirmar_talla(
            pedido,
            valor,
            nota=nota,
            mensaje=mensaje,
            actor="panel",
            anillo=anillo or None,
        )
    except ValueError:
        return _aviso(
            "Esa talla no existe",
            f"«{html.escape(talla or '(vacía)')}» no es una talla del mandril.",
            "Escoge una de la lista (van de 4 a 14, con cuartos: 7¼, 7½, 7¾). La "
            "talla del pedido no cambió y no se le mandó nada a la clienta.",
            token,
            extra=guardado,
            status=400,
        )
    log.info("panel: %s talla %s", pedido.codigo, talla_texto(valor))
    return RedirectResponse(f"/panel?token={token}", status_code=303)


@router.post("/talla-charla")
def confirmar_talla_de_la_charla(
    token: str = "",
    conv: str = Form(...),
    talla: str = Form(""),
    nota: str = Form(""),
    mensaje: str = Form(""),
):
    """Regla de Lía (29/09): confirma la talla ANTES del abono."""
    _exigir_token(token)
    c = get_container()
    valor = leer_talla(talla)
    try:
        if valor is None:
            raise ValueError(talla)
        c.confirmar_talla_de_conversacion(
            conv, valor, nota=nota, mensaje=mensaje, actor="panel"
        )
    except ValueError:
        return _aviso(
            "Esa talla no existe",
            f"«{html.escape(talla or '(vacía)')}» no es una talla del mandril.",
            "Escoge una de la lista (van de 4 a 14, con cuartos: 7¼, 7½, 7¾). No se "
            "le mandó nada a la clienta.",
            token,
            extra=_no_salio(mensaje, nota),
            status=400,
        )
    log.info("panel: talla %s confirmada en %s", talla_texto(valor), conv)
    return RedirectResponse(f"/panel?token={token}", status_code=303)


@router.post("/datos")
async def guardar_datos(request: Request, token: str = ""):
    """✏️ Datos del pedido: lo que Lía corrige o completa a mano (29/09)."""
    from app.domain.edicion import EdicionInvalida

    _exigir_token(token)
    c = get_container()
    formulario = await request.form()
    datos = {k: str(v) for k, v in formulario.items() if k != "pedido_id"}
    if "recoge_presente" in datos and "recoge" not in datos:
        datos["recoge"] = ""
    datos.pop("recoge_presente", None)
    pedido = c.orders.get(str(formulario.get("pedido_id") or ""))
    if pedido is None:
        return _aviso(
            "No encontré ese pedido",
            "Ese pedido ya no existe (se borró, o era de una prueba que se reinició).",
            "Vuelve al taller: la página se actualiza con los pedidos de ahora.",
            token,
            status=404,
        )
    try:
        cambios = c.editar_pedido(pedido, datos, actor="panel")
    except EdicionInvalida as exc:
        return _aviso(
            "Eso no se pudo guardar",
            html.escape(str(exc)),
            "Corrígelo y vuelve a guardar. No se cambió nada del pedido.",
            token,
            status=400,
        )
    log.info("panel: %s editado (%s)", pedido.codigo, "; ".join(cambios) or "sin cambios")
    return RedirectResponse(f"/panel?token={token}", status_code=303)


@router.get("/datos.csv")
def exportar_datos(token: str = "") -> Response:
    """Todos los pedidos, una fila cada uno, para abrir en Excel (29/09)."""
    _exigir_token(token)
    c = get_container()
    if c.analitica is None:
        raise HTTPException(status_code=404, detail="sin tabla de análisis")
    c.refrescar_analitica()
    hoy = datetime.now(UTC).date().isoformat()
    return Response(
        content=c.analitica.csv().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": (f"attachment; filename=pedidos-{hoy}.csv")},
    )


@router.get("/envios", response_class=HTMLResponse)
def ver_envios(token: str = "") -> HTMLResponse:
    """Cuánto cuesta el envío, a todo el país y por ciudad (29/09)."""
    _exigir_token(token)
    c = get_container()
    fletes = getattr(c.bot._mundo, "fletes", None)
    tok = html.escape(token)
    cuerpo = [
        _cabecera("Envíos · Luna Joyas"),
        "<header><h1>Envíos</h1><div class=sub>"
        f"<a href='/panel?token={tok}'>← taller</a> · "
        f"<a href='/panel/colores?token={tok}'>colores</a> · "
        f"<a href='/panel/flujo?token={tok}'>el flujo</a></div></header><main>",
    ]
    if fletes is None or not hasattr(fletes, "tarifa_unica"):
        cuerpo.append("<div class=vacio>La tabla de envíos no está disponible.</div>")
        return HTMLResponse("".join(cuerpo) + "</main></body></html>")
    general = fletes.costo_por_defecto
    ciudades = fletes.ciudades()
    distintas = [f for f in ciudades if f.costo_cop != general]
    cuerpo += [
        "<section><article>",
        f"<h3>Envío nacional: {formatear_cop(general)}</h3>",
        "<p>Es lo que el bot le dice a la clienta cuando pregunta por el envío, lo "
        "que va en las cuentas del abono («se cancela al recibir») y en el cobro "
        "del saldo («con envío incluido»). Se cobra a cualquier ciudad que no tenga "
        "un precio propio en la lista de abajo.</p>",
        "<p class=ayuda>Cada pedido guarda el envío que se le cotizó al tomarlo: "
        "cambiar el precio aquí no cambia lo que ya se le prometió a nadie.</p>",
        f"<form method=post action='/panel/envios?token={tok}' "
        "onsubmit=\"return confirm('¿Poner este precio a TODAS las ciudades?')\">"
        "<input type=hidden name=accion value=todas>"
        "<label class=campo>Mismo precio para todo el país"
        f"<input name=costo value='{general}' inputmode=numeric></label>"
        "<div class=botones><button class=principal>Aplicar a todas</button></div>"
        "</form></article></section>",
        "<section><h2>Por ciudad</h2>",
        "<p class=ayuda>"
        + (
            f"Hoy todas pagan lo mismo ({formatear_cop(general)})."
            if not distintas
            else f"{len(distintas)} ciudad(es) con precio propio."
        )
        + " Para cobrarle distinto a una ciudad, cámbiale el número. Si una ciudad "
        "no está, se le cobra el nacional.</p>",
    ]
    for f in ciudades:
        cuerpo.append(
            f"<article><form method=post action='/panel/envios?token={tok}' class=fila>"
            "<input type=hidden name=accion value=ciudad>"
            f"<input type=hidden name=ciudad value='{html.escape(f.ciudad)}'>"
            f"<span><b>{html.escape(f.ciudad)}</b> "
            f"<span class=ayuda>{html.escape(f.departamento)}</span></span>"
            f"<span><input name=costo value='{f.costo_cop}' inputmode=numeric size=8> "
            "<button>Guardar</button></span></form></article>"
        )
    cuerpo.append(
        f"<article><form method=post action='/panel/envios?token={tok}'>"
        "<input type=hidden name=accion value=ciudad>"
        "<label class=campo>Agregar una ciudad<input name=ciudad maxlength=60></label>"
        "<label class=campo>Precio del envío"
        f"<input name=costo value='{general}' inputmode=numeric></label>"
        "<div class=botones><button>Agregar</button></div></form></article>"
        "</section></main></body></html>"
    )
    return HTMLResponse("".join(cuerpo))


@router.post("/envios")
def guardar_envios(
    token: str = "",
    accion: str = Form(...),
    costo: str = Form(""),
    ciudad: str = Form(""),
):
    _exigir_token(token)
    c = get_container()
    fletes = getattr(c.bot._mundo, "fletes", None)
    valor = int(re.sub(r"\D", "", costo) or -1)
    try:
        if fletes is None:
            raise ValueError("la tabla de envíos no está disponible")
        if accion == "todas":
            fletes.tarifa_unica(valor)
        else:
            fletes.fijar(ciudad, valor)
    except (ValueError, TypeError) as exc:
        return _aviso(
            "Ese precio no se pudo guardar",
            html.escape(str(exc)),
            "Escribe el precio solo con números (ej.: 17500) y vuelve a intentar.",
            token,
            status=400,
        )
    log.info("panel: envío %s -> %s", ciudad or "todas", valor)
    return RedirectResponse(f"/panel/envios?token={token}", status_code=303)


#: Los números con los que Python dibuja cada piedra, en el orden de la
#: pantalla: (campo, etiqueta, mínimo, máximo, ayuda). Los tres primeros son el
#: COLOR; los otros, el ACABADO (`Acabado`): cómo brilla, sin cambiar el color.
_MANDOS = (
    ("tono", "Tono (°)", 0, 360, "el color en el círculo"),
    ("saturacion", "Saturación (%)", 0, 100, "0 = gris · 100 = color puro"),
    ("brillo", "Brillo (%)", 0, 100, "0 = negro · 100 = lo más claro"),
    ("facetas", "Facetas", 0, 100, "0 = piedra plana · 100 = muy marcadas"),
    ("destellos", "Reflejos", 0, 100, "0 = color parejo · 100 = facetas blancas"),
    ("fuego", "Fuego", 0, 100, "arcoíris del diamante · 0 = ninguno"),
)
_CAMPOS = tuple(m[0] for m in _MANDOS)

#: Ayuda de la página de Colores: dónde cae cada color en el círculo de tonos.
_RUEDA_DE_TONOS = (
    "rojo 0° · naranja 15° · amarillo 50° · verde 90–150° · celeste 195° · "
    "azul 220° · morado 255° · fucsia 330°"
)

_CSS_COLORES = """<style>
article{scroll-margin-top:80px}
.cuerpo{display:grid;gap:12px;margin-top:10px}
.vistas{display:grid;grid-template-columns:1fr 1fr;gap:8px;position:sticky;
top:74px;z-index:2;background:var(--tarjeta);padding:4px 0 6px}
.vistas figure{margin:0;text-align:center;font-size:12px;color:var(--suave)}
.vistas img{width:100%;max-height:170px;aspect-ratio:1;object-fit:contain;
border-radius:12px;background:#fff;border:1px solid var(--borde)}
@media(min-width:700px){.cuerpo{grid-template-columns:330px 1fr;
align-items:start}.vistas img{max-height:none}}
img.ahora{border-color:var(--acento)}
img.ahora.cargando{opacity:.6}
.mando{display:grid;grid-template-columns:7.5em 1fr 4.6em;gap:8px;
align-items:center;margin:6px 0;font-size:13px;color:var(--suave)}
.mando small{display:block;font-size:11px;line-height:1.2}
.mando input[type=range]{width:100%;height:22px;border-radius:11px;margin:0;
-webkit-appearance:none;appearance:none;background:#e9e1dc}
.mando input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;
width:22px;height:22px;border-radius:50%;background:#fff;border:2px solid #555;
box-shadow:0 1px 3px #0004}
.mando input[type=range]::-moz-range-thumb{width:18px;height:18px;
border-radius:50%;background:#fff;border:2px solid #555}
.mando input[type=number]{width:100%;font:inherit;font-size:14px;padding:5px 6px;
border-radius:8px;border:1px solid var(--borde)}
.grupo{margin:12px 0 2px;font-size:12px;font-weight:600;letter-spacing:.04em;
text-transform:uppercase;color:var(--suave)}
.rueda{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--suave)}
.punto{display:inline-block;width:14px;height:14px;border-radius:50%;
border:1px solid #999;vertical-align:middle;margin-right:6px}
</style>"""

#: Lo único de JavaScript del panel. Cada número tiene una barra y una casilla
#: (se mueven juntas, de a una unidad con las flechas del teclado), la rueda
#: de color llena tono, saturación y brillo, y CADA cambio redibuja la piedra
#: «Ahora» al instante. Lo que se guarda son los NÚMEROS: sin JavaScript,
#: escribir y Guardar también funciona.
_JS_COLORES = """
<script>
function hsv(h,s,v){s/=100;v/=100;const f=n=>{const k=(n+h/60)%6;
return v-v*s*Math.max(Math.min(k,4-k,1),0)};
return '#'+[f(5),f(3),f(1)].map(x=>Math.round(x*255).toString(16)
  .padStart(2,'0')).join('')}
function deHex(t){const r=parseInt(t.substr(1,2),16)/255,g=parseInt(t.substr(3,2),16)/255,
b=parseInt(t.substr(5,2),16)/255,M=Math.max(r,g,b),m=Math.min(r,g,b),d=M-m;let h=0;
if(d){h=M===r?((g-b)/d)%6:M===g?(b-r)/d+2:(r-g)/d+4;h*=60;if(h<0)h+=360}
return [Math.round(h)%360,Math.round(M?d/M*100:0),Math.round(M*100)]}
const CAMPOS=%CAMPOS%;
document.querySelectorAll('form.color').forEach(f=>{
 const num=c=>f.querySelector('input[type=number][name='+c+']'),
  barra=c=>f.querySelector('input[type=range][data-de='+c+']'),
  rueda=f.querySelector('input[type=color]'),punto=f.querySelector('.punto'),
  pend=f.querySelector('.pendiente'),ahora=f.querySelector('img.ahora'),
  antes=f.querySelector('img.antes'),base=ahora.dataset.base;
 let cargando=false,otra=false;
 const url=()=>base+CAMPOS.map(c=>'&'+c+'='+num(c).value).join('');
 const pedir=()=>{if(cargando){otra=true;return}cargando=true;otra=false;
  ahora.classList.add('cargando');ahora.src=url()};
 const listo=()=>{cargando=false;ahora.classList.remove('cargando');if(otra)pedir()};
 ahora.addEventListener('load',listo);ahora.addEventListener('error',listo);
 const pintar=()=>{const h=+num('tono').value,s=+num('saturacion').value,
  v=+num('brillo').value,t=hsv(h,s,v);rueda.value=t;punto.style.background=t;
  barra('saturacion').style.background='linear-gradient(90deg,'+hsv(h,0,v)+','+
   hsv(h,100,v)+')';
  barra('brillo').style.background='linear-gradient(90deg,#000,'+hsv(h,s,100)+')'};
 const cambio=()=>{pend.hidden=false;pintar();pedir()};
 CAMPOS.forEach(c=>{const n=num(c),b=barra(c);
  b.addEventListener('input',()=>{n.value=b.value;cambio()});
  n.addEventListener('input',()=>{if(n.value!==''){b.value=n.value;cambio()}})});
 f.querySelector('input[name=nombre]').addEventListener('input',()=>{pend.hidden=false});
 rueda.addEventListener('input',()=>{deHex(rueda.value).forEach((x,i)=>{
  num(CAMPOS[i]).value=x;barra(CAMPOS[i]).value=x});cambio()});
 f.querySelector('button.fabrica').addEventListener('click',()=>{
  const d=JSON.parse(f.dataset.fabrica);CAMPOS.forEach(c=>{num(c).value=d[c];
  barra(c).value=d[c]});cambio()});
 f.querySelector('button.deshacer').addEventListener('click',()=>{f.reset();
  setTimeout(()=>{pintar();pend.hidden=true;ahora.src=antes.src},0)});
 pintar();});
</script>
""".replace("%CAMPOS%", "[" + ",".join(f"'{c}'" for c in _CAMPOS) + "]")


def _prueba_de(clave: str, valores: dict[str, str]):
    """(color, tintes, acabados) con los números de la pantalla.

    Lo que no venga se toma de lo guardado; si no viene nada, tintes y
    acabados son None y se dibuja exactamente lo guardado."""
    from app.domain.personalizacion import (
        ACABADO_COLOR,
        HEX_COLOR,
        Acabado,
        ColorCircon,
        hex_a_hsv,
        hsv_a_hex,
    )

    color = ColorCircon(clave)
    if all(valores.get(c, "") == "" for c in _CAMPOS):
        return color, None, None
    guardado = dict(
        zip(("tono", "saturacion", "brillo"), hex_a_hsv(HEX_COLOR[color]), strict=True)
    )
    guardado.update(vars(ACABADO_COLOR[color]))
    n = {
        c: float(valores[c]) if valores.get(c, "") != "" else float(guardado[c])
        for c in _CAMPOS
    }
    tinte = hsv_a_hex(n["tono"], n["saturacion"], n["brillo"])
    if all(n[c] == guardado[c] for c in ("tono", "saturacion", "brillo")):
        # Los números de la pantalla van redondeados: si no se tocaron, se
        # queda el tinte exacto guardado (#947FBE no se vuelve #9580BF).
        tinte = HEX_COLOR[color]
    acabado = Acabado(*(round(n[c]) for c in ("facetas", "destellos", "fuego")))
    return color, {color: tinte}, {color: acabado}


#: Lado mayor de la imagen «Ahora» del panel: se redibuja con cada unidad que
#: se mueve, así que va liviana. La de la clienta sale en tamaño completo.
_LADO_DE_LA_PRUEBA = 520


@router.get("/colores/vista")
def vista_de_un_color(
    token: str = "",
    clave: str = "",
    tono: str = "",
    saturacion: str = "",
    brillo: str = "",
    facetas: str = "",
    destellos: str = "",
    fuego: str = "",
):
    """La huellita de un color, con lo guardado o con lo que se está probando.

    Sin números: lleva a la imagen guardada, la MISMA que recibe la clienta.
    Con números: la dibuja en el momento y la devuelve SIN guardarla (ni en la
    base ni en disco). Lo que se le manda a la clienta no cambia hasta Guardar.
    """
    import io

    from app.domain.personalizacion import Huellita

    _exigir_token(token)
    c = get_container()
    valores = {
        "tono": tono,
        "saturacion": saturacion,
        "brillo": brillo,
        "facetas": facetas,
        "destellos": destellos,
        "fuego": fuego,
    }
    try:
        color, tintes, acabados = _prueba_de(clave, valores)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    render = getattr(c, "render", None)
    if render is None:
        raise HTTPException(status_code=404, detail="no se pudo dibujar")
    huellita = Huellita(corazon=color, dedos=color)
    if tintes is None:
        nombre = render.previsualizar([huellita])
        if not nombre:
            raise HTTPException(status_code=404, detail="no se pudo dibujar")
        return RedirectResponse(f"/media/{nombre}", status_code=302)
    try:
        imagen = render.dibujar([huellita], tintes, acabados)
    except Exception as exc:
        log.warning("panel: no se pudo dibujar la prueba de %s (%s)", clave, exc)
        raise HTTPException(status_code=404, detail="no se pudo dibujar") from exc
    imagen.thumbnail((_LADO_DE_LA_PRUEBA, _LADO_DE_LA_PRUEBA))
    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=85)
    return Response(
        salida.getvalue(),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


def _mando(campo: str, etiqueta: str, minimo: int, maximo: int, ayuda: str, valor) -> str:
    """Una fila: barra + casilla con el mismo número. Solo la casilla se envía."""
    tonos = (
        " style='background:linear-gradient(90deg,#f00,#ff0,#0f0,#0ff,#00f,#f0f,#f00)'"
        if campo == "tono"
        else ""
    )
    return (
        f"<label class=mando><span>{etiqueta}<small>{ayuda}</small></span>"
        f"<input type=range data-de={campo} min={minimo} max={maximo} step=1 "
        f"value='{valor}'{tonos} aria-label='{etiqueta}'>"
        f"<input type=number name={campo} min={minimo} max={maximo} step=1 "
        f"value='{valor}'></label>"
    )


@router.get("/colores", response_class=HTMLResponse)
def ver_colores(token: str = "") -> HTMLResponse:
    """Los colores de circón: nombre, color y acabado de cada bolsita (30/09)."""
    import json

    from app.domain.personalizacion import (
        ACABADO_DE_FABRICA,
        NOMBRE_EN_LA_FOTO,
        TINTE_DE_FABRICA,
        Acabado,
        ColorCircon,
        hex_a_hsv,
    )

    _exigir_token(token)
    c = get_container()
    tok = html.escape(token)
    fabrica = Acabado()
    blanco = ACABADO_DE_FABRICA[ColorCircon.BLANCO]
    cuerpo = [
        _cabecera("Colores · Luna Joyas"),
        _CSS_COLORES,
        "<header><h1>Colores</h1><div class=sub>"
        f"<a href='/panel?token={tok}'>← taller</a> · "
        f"<a href='/panel/envios?token={tok}'>envíos</a> · "
        f"<a href='/panel/flujo?token={tok}'>el flujo</a></div></header><main>",
    ]
    colores = getattr(c, "colores", None)
    if colores is None:
        cuerpo.append("<div class=vacio>La tabla de colores no está disponible.</div>")
        return HTMLResponse("".join(cuerpo) + "</main></body></html>")
    cuerpo += [
        "<section><article>",
        "<h3>Las 14 bolsitas del muestrario</h3>",
        "<p>La <b>misma lista</b> sirve para el corazón y para los deditos. El "
        "<b>nombre</b> es como se lo dice el bot a la clienta (en el resumen, en la "
        "foto de «así se te va a ver» y en lo que escribe la IA). Los "
        "<b>números</b> son con los que se dibuja esa piedra en la vista previa.</p>",
        "<p class=ayuda>Mueve una barra (o escribe el número, o usa las flechas "
        "del teclado de a una unidad) y la imagen <b>Ahora</b> se redibuja al "
        "instante; <b>Guardado</b> es la que recibe la clienta hoy. Nada cambia "
        "para ella hasta tocar <b>Guardar</b>; <b>Deshacer</b> vuelve a lo "
        "guardado.</p>",
        "<p class=ayuda><b>Color</b>: el cuerpo de la piedra da, en promedio, "
        "exactamente el color de tono, saturación y brillo (o el de la rueda). "
        f"Tono: {_RUEDA_DE_TONOS}. <b>Acabado</b>: cómo brilla, sin cambiar el "
        "color. <b>Facetas</b> marca más o menos las caras de la piedra; "
        "<b>reflejos</b> le pone luz blanca a las caras más claras (0 = color "
        "parejo, 100 = como un hielo) y <b>fuego</b> deja pasar el arcoíris del "
        "diamante de la foto. En los colores oscuros, pocos reflejos: si no, se "
        f"ven grises. De fábrica: facetas {fabrica.facetas}, reflejos "
        f"{fabrica.destellos}, fuego {fabrica.fuego}; el <b>blanco</b> va con "
        f"{TINTE_DE_FABRICA[ColorCircon.BLANCO]}, facetas {blanco.facetas}, reflejos "
        f"{blanco.destellos} y fuego {blanco.fuego}: así es igual a la foto del "
        "diamante. <b>De fábrica</b> pone los números de fábrica de esa bolsita "
        "(para verlos; se guardan con Guardar).</p>",
        "<p class=ayuda><b>Al guardar se actualiza todo a la vez</b>, sin "
        "reiniciar: el resumen y el pie de las fotos, lo que dice la IA, lo que el "
        "bot entiende cuando la clienta escribe ese nombre y la vista previa de "
        "cualquier anillo con ese color. Lo único que no cambia sola es la "
        "<a href='/media/muestrario_circones' target=_blank>foto del muestrario</a>"
        ", que tiene los nombres escritos: si cambias un nombre, el color lo "
        "avisa.</p>",
        "<p class=ayuda>Cambiar un nombre no cambia los pedidos ya tomados "
        "(guardan la bolsita, no el nombre). Agregar o quitar una bolsita sí se "
        "hace en el código.</p>",
        "</article></section><section>",
    ]
    for fila in colores.todos():
        tono, saturacion, brillo = hex_a_hsv(fila.tinte)
        valores = {
            "tono": tono,
            "saturacion": saturacion,
            "brillo": brillo,
            **vars(fila.acabado),
        }
        clave = fila.color.value
        nombre = html.escape(fila.nombre)
        vista = f"/panel/colores/vista?token={tok}&clave={clave}"
        mandos = [_mando(*m, valores[m[0]]) for m in _MANDOS]
        de_fabrica = dict(
            zip(
                ("tono", "saturacion", "brillo"),
                hex_a_hsv(TINTE_DE_FABRICA[fila.color]),
                strict=True,
            ),
            **vars(ACABADO_DE_FABRICA[fila.color]),
        )
        en_la_foto = NOMBRE_EN_LA_FOTO.get(fila.color, fila.nombre)
        aviso = (
            "<div class=aviso>La foto del muestrario dice "
            f"«{html.escape(en_la_foto)}»: hay que cambiarla para que coincida "
            "(o volver al nombre de la foto).</div>"
            if fila.nombre != en_la_foto
            else ""
        )
        cuerpo.append(
            f"<article id='{clave}'><form method=post class=color "
            f"action='/panel/colores?token={tok}' data-clave='{clave}' "
            f"data-fabrica='{html.escape(json.dumps(de_fabrica))}'>"
            f"<input type=hidden name=clave value='{clave}'>"
            f"<label class=campo><span><span class=punto "
            f"style='background:{fila.tinte}'></span>Nombre · bolsita {clave}</span>"
            f"<input name=nombre value='{nombre}' maxlength=30></label>"
            + aviso
            + "<div class=cuerpo><div class=vistas>"
            f"<figure><img class=antes src='{vista}' alt='{nombre} guardado'>"
            "<figcaption>Guardado (lo que ve la clienta)</figcaption></figure>"
            f"<figure><img class=ahora src='{vista}' data-base='{vista}' "
            f"alt='{nombre} probando'><figcaption>Ahora</figcaption></figure>"
            "</div><div class=mandos>"
            "<div class=grupo>Color</div>"
            + "".join(mandos[:3])
            + "<div class=rueda><input type=color "
            f"value='{fila.tinte.lower()}' aria-label='escoger el color con la rueda'>"
            "o escógelo con la rueda</div>"
            "<div class=grupo>Acabado</div>"
            + "".join(mandos[3:])
            + "<div class=botones><button class=principal>Guardar</button>"
            "<button type=button class=deshacer>Deshacer</button>"
            "<button type=button class=fabrica>De fábrica</button>"
            "<span class='ayuda pendiente' hidden>Sin guardar: la clienta sigue "
            "viendo «Guardado»</span></div>"
            "</div></div></form></article>"
        )
    cuerpo.append("</section></main>" + _JS_COLORES + "</body></html>")
    return HTMLResponse("".join(cuerpo))


@router.post("/colores")
def guardar_color(
    token: str = "",
    clave: str = Form(...),
    nombre: str = Form(""),
    tono: str = Form(""),
    saturacion: str = Form(""),
    brillo: str = Form(""),
    facetas: str = Form(""),
    destellos: str = Form(""),
    fuego: str = Form(""),
):
    _exigir_token(token)
    c = get_container()
    valores = {
        "tono": tono,
        "saturacion": saturacion,
        "brillo": brillo,
        "facetas": facetas,
        "destellos": destellos,
        "fuego": fuego,
    }
    try:
        colores = getattr(c, "colores", None)
        if colores is None:
            raise ValueError("la tabla de colores no está disponible")
        color, tintes, acabados = _prueba_de(clave, valores)
        if tintes is None or acabados is None:
            raise ValueError("faltan los números del color")
        fila = colores.fijar(color, nombre, tintes[color], acabados[color])
    except (ValueError, TypeError) as exc:
        return _aviso(
            "Ese color no se pudo guardar",
            html.escape(str(exc)),
            "Revisa el nombre (solo letras) y los números (tono de 0 a 360; "
            "saturación, brillo, facetas, reflejos y fuego de 0 a 100) y vuelve a "
            "intentar.",
            token,
            status=400,
        )
    log.info("panel: color %s -> %s %s %s", clave, fila.nombre, fila.tinte, fila.acabado)
    return RedirectResponse(f"/panel/colores?token={token}#{clave}", status_code=303)


#: FastAPI espera estos objetos como valor por defecto, pero llamarlos en la
#: firma es una llamada que se evalúa una sola vez al importar. Se crean aquí,
#: a nivel de módulo, que es lo mismo y además lo deja explícito.
_CAMPO_PEDIDO = Form(...)
_CAMPO_ARCHIVOS = File(...)


# ══════════════════════════════════════════════════════════════════════════
#  CHATS: leer y contestar a mano, desde el computador o el celular
# ══════════════════════════════════════════════════════════════════════════
#
#  Mientras alguien escribe aquí, el bot se calla en ESA conversación
#  (`app.domain.atencion`). Vuelve solo a las 12 horas, o antes con el botón
#  «que siga el bot». Es lo que evita las dos voces en el mismo chat.


def _cuando(marca: str | None) -> str:
    """La hora como la lee una persona: «14:05» o «ayer 14:05»."""
    if not marca:
        return ""
    try:
        momento = datetime.fromisoformat(marca)
    except ValueError:
        return ""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)
    local = momento.astimezone(HORA_COLOMBIA)
    hoy = datetime.now(HORA_COLOMBIA).date()
    dias = (hoy - local.date()).days
    if dias == 0:
        return local.strftime("%H:%M")
    if dias == 1:
        return f"ayer {local:%H:%M}"
    return f"{local:%d/%m %H:%M}"


#: Los periodos del tablero: lo que se mira a diario, por semana y por mes.
PERIODOS = {"hoy": "Hoy", "7": "7 días", "30": "30 días"}


def _desde(periodo: str) -> str:
    """Inicio del periodo en UTC. «Hoy» empieza a medianoche de Colombia."""
    ahora = datetime.now(HORA_COLOMBIA)
    if periodo == "hoy":
        inicio = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        inicio = ahora - timedelta(days=int(periodo))
    return inicio.astimezone(UTC).isoformat()


@router.get("/metricas", response_class=HTMLResponse)
def ver_metricas(token: str = "", periodo: str = "7") -> HTMLResponse:
    """Cómo va el negocio y cómo va el bot. Números agregados, sin datos de nadie."""
    from app.adapters.repositories.tablero import tablero

    _exigir_token(token)
    periodo = periodo if periodo in PERIODOS else "7"
    c = get_container()
    t = tablero(c.db, _desde(periodo))
    bot = t["bot"]
    t_ = html.escape(token)

    pestañas = " · ".join(
        f"<b>{nombre}</b>"
        if clave == periodo
        else f"<a href='/panel/metricas?token={t_}&periodo={clave}'>{nombre}</a>"
        for clave, nombre in PERIODOS.items()
    )
    respuesta = (
        f"{t['respuesta_p50_s']:.0f} s" if t["respuesta_p50_s"] is not None else "—"
    )

    def bloque(titulo: str, filas: list[tuple[str, object]]) -> str:
        cuerpo = "".join(
            f"<div class=ayuda>{html.escape(n)}: <b>{html.escape(str(v))}</b></div>"
            for n, v in filas
        )
        return f"<article><h3>{html.escape(titulo)}</h3>{cuerpo}</article>"

    negocio = [
        ("Conversaciones con clientas", t["conversaciones"]),
        ("Clientas nuevas", t["nuevas"]),
        ("Mensajes recibidos / enviados", f"{t['recibidos']} / {t['enviados']}"),
        ("Tiempo de respuesta (mediana)", respuesta),
        ("Pedidos armados", t["pedidos"]),
        ("Pedidos pagados", t["pagados"]),
        ("Ventas", formatear_cop(t["ventas_cop"])),
        ("Conversión (pagados / nuevas)", f"{t['conversion_pct']} %"),
        ("Atendidas a mano ahora", t["a_mano_ahora"]),
    ]
    if bot.get("turnos"):
        del_bot = [
            ("Turnos contestados", bot["turnos"]),
            (
                "Modelo básico / potente",
                f"{bot['basico_pct']} % / {bot['potente_pct']} %",
            ),
            ("Pasados a una persona", bot["a_una_persona"]),
            ("Corregidos por las reglas", bot["acciones_corregidas"]),
            ("Errores", bot["errores"]),
            (
                "Latencia p50 / p95",
                f"{bot['latencia_p50_ms']} / {bot['latencia_p95_ms']} ms",
            ),
            ("Costo del modelo", f"USD {bot['costo_total_usd']}"),
            ("Costo por turno", f"USD {bot['costo_por_turno_usd']}"),
        ]
    else:
        del_bot = [("Turnos contestados", 0)]

    cuerpo = [
        _cabecera("Métricas · Luna Joyas"),
        "<header><h1>Métricas</h1>",
        f"<div class=sub>{pestañas} · "
        f"<a href='/panel?token={t_}'>taller</a> · "
        f"<a href='/panel/chats?token={t_}'>conversaciones</a></div>"
        "</header><main><section>",
        bloque("El negocio", negocio),
        bloque("El bot", del_bot),
        "</section></main></body></html>",
    ]
    return HTMLResponse("".join(cuerpo))


@router.get("/chats", response_class=HTMLResponse)
def ver_chats(token: str = "") -> HTMLResponse:
    _exigir_token(token)
    c = get_container()
    conversaciones = c.conversaciones.recientes(limite=40)

    cuerpo = [
        _cabecera("Conversaciones · Luna Joyas"),
        "<header><h1>Conversaciones</h1>",
        f"<div class=sub>{len(conversaciones)} recientes · "
        f"<a href='/panel?token={html.escape(token)}'>ver el taller</a> · "
        f"<a href='/panel/metricas?token={html.escape(token)}'>métricas</a></div>"
        "</header><main><section>",
    ]
    if not conversaciones:
        cuerpo.append("<div class=vacio>Todavía no ha escrito nadie ✨</div>")
    for fila in conversaciones:
        conv = fila["conversation_id"]
        quien = "tú" if fila.get("direccion") == "OUT" else "ella"
        texto = (fila.get("texto") or _sin_texto(fila))[:90]
        pausada = c.bot._mundo.la_atiende_una_persona(conv)
        marca = "<span class=cuenta>a mano</span>" if pausada else ""
        cuerpo.append(
            f"<article><a href='/panel/chat?conv={html.escape(conv)}"
            f"&token={html.escape(token)}'>"
            f"<h3>{html.escape(_bonito(fila.get('channel_user_id') or conv))}{marca}</h3>"
            f"<div class=ayuda>{html.escape(quien)}: {html.escape(texto)} · "
            f"{html.escape(_cuando(fila.get('created_at')))}</div></a></article>"
        )
    cuerpo.append("</section></main></body></html>")
    return HTMLResponse("".join(cuerpo))


def _bonito(user_id: str) -> str:
    """El teléfono como lo lee una persona."""
    numero = user_id.split(":")[-1]
    if numero.startswith("57") and len(numero) == 12:
        return f"+57 {numero[2:5]} {numero[5:8]} {numero[8:]}"
    return numero


@router.get("/chat", response_class=HTMLResponse)
def ver_chat(conv: str = "", token: str = "") -> HTMLResponse:
    _exigir_token(token)
    c = get_container()
    mensajes = c.conversaciones.historial(conv, limite=40)
    ctx = c.bot._mundo.contexto(conv)
    faltan = minutos_restantes(ctx.humano_hasta)
    abierta = c.conversaciones.ventana_abierta(conv)

    cuerpo = [
        _cabecera(f"Chat {_bonito(conv)}"),
        f"<header><h1>{html.escape(_bonito(conv))}</h1><div class=sub>"
        f"<a href='/panel/chats?token={html.escape(token)}'>← conversaciones</a>"
        "</div></header><main><section>",
    ]
    if faltan:
        horas, minutos = divmod(faltan, 60)
        cuerpo.append(
            "<p class=ayuda>La estás atendiendo tú: el bot no contesta aquí "
            f"por {horas} h {minutos} min.</p>"
            f"<form method=post action='/panel/devolver?token={html.escape(token)}'>"
            f"<input type=hidden name=conv value='{html.escape(conv)}'>"
            "<button type=submit>Que siga el bot</button></form>"
        )
    else:
        cuerpo.append(
            "<p class=ayuda>Contesta el bot. Si escribes aquí, se calla 12 horas "
            "en esta conversación.</p>"
        )

    cuerpo.append("<div class=chat>")
    for mensaje in mensajes:
        lado = "mio" if mensaje.get("direccion") == "OUT" else "suyo"
        medio = _medio_del_mensaje(mensaje)
        texto = html.escape(mensaje.get("texto") or "").replace("\n", "<br>")
        if not texto and not medio:
            texto = html.escape(_sin_texto(mensaje))
        cuerpo.append(
            f"<div class='burbuja {lado}'>{medio}{texto}"
            f"<span class=hora>{html.escape(_cuando(mensaje.get('created_at')))}</span>"
            "</div>"
        )
    cuerpo.append("</div>")

    if abierta:
        cuerpo.append(
            f"<form method=post action='/panel/responder?token={html.escape(token)}' "
            "class=responder>"
            f"<input type=hidden name=conv value='{html.escape(conv)}'>"
            "<textarea name=texto rows=3 placeholder='Escríbele…' required></textarea>"
            "<button class=principal type=submit>Enviar</button></form>"
        )
    else:
        cuerpo.append(
            "<p class=ayuda>Pasaron más de 24 horas desde su último mensaje: "
            "WhatsApp solo deja escribirle con una plantilla aprobada.</p>"
        )
    cuerpo.append("</section></main></body></html>")
    return HTMLResponse("".join(cuerpo))


@router.post("/responder")
def responder(token: str = "", conv: str = Form(...), texto: str = Form(...)) -> Response:
    """Manda lo que escribió la persona y calla al bot en esa conversación."""
    _exigir_token(token)
    c = get_container()
    limpio = (texto or "").strip()
    if not limpio:
        return RedirectResponse(f"/panel/chat?conv={conv}&token={token}", status_code=303)

    canal, _, user_id = conv.partition(":")
    equivalente = {"wa": Channel.WHATSAPP, "ig": Channel.INSTAGRAM}.get(canal)
    if equivalente is None:
        raise HTTPException(status_code=400, detail="conversación desconocida")

    # Por la puerta única: sale hacia la clienta y queda en Chatwoot, para que
    # la conversación esté completa donde Lía atiende (auditoría del 26/09).
    c.enviar_a_la_clienta(
        conv,
        OutboundMessage(
            channel=equivalente,
            to=user_id,
            kind="text",
            text=limpio[:4000],
            idempotency_key=f"humano:{new_id()}",
        ),
    )
    # El orden importa: primero se encola, y solo si eso salió bien se calla
    # al bot. Al revés, un fallo dejaría la conversación muda.
    # Y en Chatwoot queda asignada a la persona, no a VentaBot (09/10).
    from app.infra.quien_atiende import la_toma_una_persona

    la_toma_una_persona(c, conv, c.settings.chatwoot_persona_del_panel or None)
    c.bot._mundo.anotar_mensaje_de_humano(conv, limpio)
    log.info("respuesta a mano en %s (%s caracteres)", conv, len(limpio))
    return RedirectResponse(f"/panel/chat?conv={conv}&token={token}", status_code=303)


@router.post("/devolver")
def devolver(token: str = "", conv: str = Form(...)) -> Response:
    """Quien atendía suelta la conversación: el bot vuelve a contestar, y en
    Chatwoot vuelve a quedar asignada a VentaBot."""
    _exigir_token(token)
    from app.infra.quien_atiende import devolver_al_bot

    devolver_al_bot(get_container(), conv)
    return RedirectResponse(f"/panel/chat?conv={conv}&token={token}", status_code=303)


@router.post("/fotos")
async def subir_fotos(
    token: str = "",
    pedido_id: str = _CAMPO_PEDIDO,
    archivos: list[UploadFile] = _CAMPO_ARCHIVOS,
):
    """Lía sube las fotos del anillo terminado desde el celular.

    El `<input type=file accept='image/*'>` le ofrece la cámara y la galería
    directamente: no tiene que salir del panel, buscar el chat y adjuntar.
    """
    _exigir_token(token)
    c = get_container()
    pedido = c.orders.get(pedido_id)
    if pedido is None:
        raise HTTPException(status_code=404, detail="pedido no encontrado")

    almacen = _almacen()
    nombres, problemas = list(pedido.fotos), []
    for archivo in archivos:
        datos = await archivo.read()
        if not datos:
            continue
        try:
            nombres.append(almacen.guardar(datos).nombre)
        except FotoInvalida as exc:
            # Se avisa y se sigue con las demás: que una foto pesada tumbe la
            # subida entera obligaría a Lía a adivinar cuál era.
            problemas.append(f"{archivo.filename}: {exc}")
            log.warning("foto rechazada (%s): %s", archivo.filename, exc)

    c.orders.guardar_pedido(pedido.model_copy(update={"fotos": nombres}))
    log.info("panel: %s tiene ahora %s foto(s)", pedido.codigo, len(nombres))
    if problemas:
        # Antes solo quedaba en el registro, y en el panel la foto simplemente
        # no aparecía: había que adivinar por qué (28/09).
        log.warning("panel: %s", " · ".join(problemas))
        subidas = len(nombres) - len(pedido.fotos)
        return _aviso(
            "Algunas fotos no se subieron",
            "<ul>" + "".join(f"<li>{html.escape(x)}</li>" for x in problemas) + "</ul>",
            (f"Las otras {subidas} sí quedaron en el pedido. " if subidas else "")
            + "Prueba con otra foto (JPG o PNG, no muy pesada) desde la galería.",
            token,
            status=400,
        )
    return RedirectResponse(f"/panel?token={token}", status_code=303)


@router.get("/foto/{nombre}")
def ver_foto(nombre: str):
    """Sirve una foto. SIN token, a propósito, y por eso el nombre es aleatorio.

    Los servidores de Meta bajan la imagen con un GET anónimo desde internet:
    no pueden mandar nuestro token. La única defensa posible es que la URL sea
    imposible de adivinar, y por eso cada archivo se guarda con 32 caracteres
    aleatorios criptográficos (ver `app.adapters.almacen_fotos`).

    Un identificador correlativo aquí (`/foto/1`, `/foto/2`) habría dejado las
    fotos de todas las clientas a la vista de cualquiera que contara.
    """
    ruta = _almacen().ruta_de(nombre)
    if ruta is None:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        ruta,
        media_type=_almacen().tipo_de(nombre),
        headers={
            # Que no se indexe ni se guarde en caches intermedias.
            "X-Robots-Tag": "noindex, nofollow",
            "Cache-Control": "private, max-age=3600",
        },
    )
