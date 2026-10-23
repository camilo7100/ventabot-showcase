"""«Marketing»: el tablero de la pauta de Instagram, para Lía (30/09).

Lo escribe el Claude de marketing (`Documents\\GitHub\\marketing-lia`) en
`PARA-EL-PANEL.md`; `SUBIR-MARKETING.cmd` lo pone en el servidor y esta página
lo muestra en cada carga. Las reglas las pone ese archivo (§3) y se cumplen:

- SOLO LECTURA y el texto TAL CUAL: no se resume, no se recalcula y no se
  reordena (el orden de cada lista es su prioridad). La única excepción la
  pide el formato: las tareas hechas van al final, atenuadas.
- Va en PESTAÑAS (`VISTAS`, 01/10): Hoy · Piloto (03/10, en
  `marketing_piloto.py`) · Números · Campañas · Creativos · Estrategia ·
  Indicadores · Biblioteca. Dentro de cada una, el orden del
  formato. Además del tablero se muestra TODA la carpeta: sus documentos
  (`markdown_seguro`) y sus tablas `datos/*.csv`, y con ellas el panel CALCULA
  KPIs, embudo y recomendaciones (`marketing_numeros`), marcado «🧮 calculado».
- Celular primero: las tareas se pliegan y cada paso es una casilla (la
  marca queda solo en ese celular: es la lista de quien sigue la receta, no
  contenido). Las plantillas llevan botón de copiar; los enlaces de Instagram
  abren fuera; arriba, la revisión y la fecha.
- Las gráficas van en barras horizontales, no verticales como sugiere el
  formato: 17 meses en vertical no caben legibles en un celular.
- A la defensiva: una clave que no se conoce se ignora, y una sección que
  llega mal se salta con un aviso. Nunca un error 500 por el contenido.

Para que el formato crezca «poco a poco»: una clave nueva se muestra
agregando su función `_seccion_…` y poniéndola en su pestaña de `VISTAS`.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.api import markdown_seguro as md
from app.domain import marketing_estandar as estandar
from app.domain import marketing_numeros as num
from app.domain.marketing import Tablero, leer_tablero
from app.domain.pricing import formatear_cop

log = logging.getLogger("ventabot.panel")

#: Sin `ZoneInfo`: en Windows no hay base de zonas horarias (ver `panel.py`).
_COLOMBIA = timezone(timedelta(hours=-5), "America/Bogota")

_MESES = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)

#: Los valores cerrados del formato, con cómo se le dicen a Lía. Un valor que
#: no esté aquí se muestra tal cual (con espacios en vez de «_»).
CUANDO = {
    "hoy": "Hoy",
    "esta_semana": "Esta semana",
    "cada_lunes": "Cada lunes",
    "con_cada_entrega": "Con cada entrega",
    "decision": "Decisión",
    "este_mes": "Este mes",
}
QUIEN = {"lia": "Lía", "camilo": "Camilo", "ambos": "Lía y Camilo"}
ESTADO_TAREA = {
    "pendiente": "Pendiente",
    "en_curso": "En curso",
    "hecho": "Hecho ✓",
    "descartado": "Descartada",
}
ESTADO_PRUEBA = {
    "por_lanzar": "Por lanzar",
    "corriendo": "Corriendo",
    "terminada": "Terminada",
    "en_cola": "En cola",
    "descartada": "Descartada",
}
ESTADO_REEL = {
    "en_pauta": "En pauta",
    "gastado": "Gastado",
    "de_reserva": "De reserva",
    "pedir_permiso": "Pedir permiso",
    "retirado": "Retirado",
}
CONFIANZA = {
    "baja": "Confianza baja",
    "media": "Confianza media",
    "alta": "Confianza alta",
}

#: Si la revisión tiene más de estos días, se avisa: Lía podría estar
#: siguiendo un plan que ya cambió.
DIAS_PARA_AVISAR = 10

ESTILO_MARKETING = """
.periodo{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:14px;
margin:8px 0}
.periodo select{font:inherit;padding:5px 8px;border-radius:8px}
.periodo button{padding:5px 12px}
.revision{font-size:13px;color:var(--suave);margin:2px 0 0}
.alerta{border-radius:10px;padding:10px 12px;margin:8px 0;font-size:14px}
.alerta b{display:block;margin-bottom:2px}
.alerta.urgente{background:#fbe9e7;border-left:4px solid #c0392b}
.alerta.aviso{background:#fff6e0;border-left:4px solid #d39b1f}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0}
.chip{font-size:12px;padding:2px 9px;border-radius:999px;background:#f1ebe8;
color:var(--texto);white-space:nowrap}
.chip.hoy,.chip.urgente{background:#fbe0dc;color:#9b2c1e}
.chip.hecho,.chip.terminada,.chip.en_pauta,.chip.alta{background:#e3f1e7;color:#2f6b45}
.chip.en_curso,.chip.corriendo,.chip.media{background:#fff1cf;color:#7a5a12}
.chip.pedir_permiso,.chip.por_lanzar{background:#e6edfb;color:#294f94}
details.tarea{background:var(--tarjeta);border:1px solid var(--borde);border-radius:12px;
padding:11px 13px;margin-bottom:10px}
details.tarea[open]{border-color:var(--acento)}
details.tarea summary{cursor:pointer;list-style:none}
details.tarea summary::-webkit-details-marker{display:none}
details.tarea summary::after{content:"▸ abrir";font-size:12px;color:var(--acento)}
details.tarea[open] summary::after{content:"▾ cerrar"}
details.hecho,details.descartado{opacity:.55}
.chip.avance:empty{display:none}
.chip.avance.completa{background:#e3f1e7;color:#2f6b45}
label.casilla{display:flex;gap:8px;align-items:flex-start;cursor:pointer}
label.casilla input{width:18px;height:18px;margin:2px 0 0;flex:none;
accent-color:var(--acento)}
label.casilla input:checked+span{text-decoration:line-through;color:var(--suave)}
ol.pasos>li{list-style:none;margin-left:-20px}
ol.pasos ul{list-style:none}
.formula{font-weight:600;font-size:14px;margin:0 0 6px}
.semaforo{display:grid;gap:6px;margin-top:10px}
.regla{border-radius:9px;padding:8px 10px;font-size:14px;border-left:4px solid #b9a6a0;
background:#f7f3f1}
.regla.bueno{border-color:#3f7d5a;background:#eef6f0}
.regla.malo{border-color:#c0392b;background:#fbecea}
.regla .hacer{font-weight:600;margin-top:2px}
.desliza{overflow-x:auto;margin:8px 0}
table.rentabilidad{font-size:13px;min-width:560px}
table.rentabilidad .ganancia{font-weight:700;color:var(--ok)}
table.rentabilidad td:first-child,table.rentabilidad th:first-child{position:sticky;
left:0;background:var(--tarjeta);z-index:1}
tr.g-moderada td{background:#f1f8f3}
tr.g-alta td{background:#fcf0ee}
tr.total td{font-weight:700;border-top:2px solid var(--texto)}
.leyenda i.g-moderada{background:#cfe6d6}
.leyenda i.g-alta{background:#f3cfc9}
.num{font-weight:700;color:var(--acento);margin-right:6px}
.porque{font-size:14px;color:var(--suave);margin:4px 0 8px}
ol.pasos{margin:6px 0;padding-left:20px;font-size:14px}
ol.pasos li{margin:5px 0}
ol.pasos ul{margin:4px 0;padding-left:18px}
.plantilla{background:#f7f3f1;border:1px solid var(--borde);border-radius:10px;
padding:9px 10px;margin:8px 0}
.plantilla .etiqueta{font-size:12px;color:var(--suave);margin-bottom:4px}
.plantilla pre{white-space:pre-wrap;font:inherit;font-size:14px;margin:0 0 8px}
.nota{font-size:13px;color:var(--suave);border-left:3px solid var(--borde);
padding-left:8px;margin:8px 0 0}
.cifras{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.cifra{background:var(--tarjeta);border:1px solid var(--borde);border-radius:12px;
padding:10px}
.cifra{min-width:0;overflow-wrap:anywhere}
.cifra .valor{font-size:clamp(18px,5.6vw,22px);font-weight:700;line-height:1.2}
.cifra.bueno .valor{color:var(--ok)}
.cifra.malo .valor{color:var(--alerta)}
.cifra .etiqueta{font-size:12px;color:var(--suave)}
.cifra .nota{border:0;padding:0;margin:4px 0 0;font-size:12px}
.barras{margin:8px 0}
.barra{display:grid;grid-template-columns:3.6em 1fr 5.4em;gap:6px;align-items:center;
font-size:12px;margin:3px 0}
.barra .fondo{background:#f1ebe8;border-radius:4px;height:14px}
.barra .lleno{height:14px;border-radius:4px;background:#b9a6a0}
.barra .cuanto{text-align:right;font-variant-numeric:tabular-nums}
.leyenda{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--suave);
margin:4px 0}
.leyenda i{display:inline-block;width:10px;height:10px;border-radius:2px;
margin-right:4px;vertical-align:middle}
.fuente{font-size:12px;color:var(--suave);margin-top:6px}
article.principal{border-color:var(--alerta);border-width:2px}
table.tabla{width:100%;border-collapse:collapse;font-size:14px}
table.tabla th,table.tabla td{border-bottom:1px solid var(--borde);padding:6px 4px;
text-align:right}
table.tabla th:first-child,table.tabla td:first-child{text-align:left}
.dato-par{font-size:14px;margin:4px 0}
.dato-par b{color:var(--suave);font-weight:600}
.fechas{list-style:none;padding:0;margin:0}
.fechas li{display:grid;grid-template-columns:5.6em 1fr;gap:8px;padding:7px 0;
border-bottom:1px solid var(--borde);font-size:14px}
.fechas li.clave{font-weight:600}
.fechas li.clave .dia{color:var(--acento)}
.fechas li.pasada{opacity:.5}
.fechas li.proxima{background:#fff6e0;border-radius:8px;padding:7px 6px}
.dia{color:var(--suave);white-space:nowrap}
a.fuera{display:inline-block;margin-top:6px;font-size:14px}
.pestanas{display:flex;gap:4px;margin:8px -4px -6px;overflow-x:auto;scrollbar-width:none}
.pestanas::-webkit-scrollbar{display:none}
.pestanas a{white-space:nowrap;font-size:14px;padding:7px 12px;border-radius:9px 9px 0 0;
color:var(--suave);text-decoration:none;border-bottom:3px solid transparent}
.pestanas a.activa{color:var(--texto);font-weight:700;border-bottom-color:var(--acento)}
section h2,section#alertas{scroll-margin-top:130px}
.alerta.bien{background:#eef6f0;border-left:4px solid #3f7d5a}
.chip.malo{background:#fbe0dc;color:#9b2c1e}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.kpi{background:var(--tarjeta);border:1px solid var(--borde);border-radius:12px;
padding:10px;min-width:0;overflow-wrap:anywhere}
.kpi .etiqueta{font-size:12px;color:var(--suave)}
.kpi .valor{font-size:clamp(18px,5.4vw,22px);font-weight:700;line-height:1.25}
.kpi .que{font-size:11px;color:var(--suave);margin-top:4px;line-height:1.3}
.delta{display:inline-block;font-size:12px;font-weight:600;border-radius:999px;
padding:1px 7px;background:#f1ebe8}
.delta.bueno{background:#e3f1e7;color:#2f6b45}
.delta.malo{background:#fbe0dc;color:#9b2c1e}
.escalon{margin:4px 0}
.barra-embudo{background:linear-gradient(90deg,#c96f8b,#e7b3c3);color:#fff;
border-radius:8px;padding:6px 10px;font-size:14px;white-space:nowrap}
.escalon .nombre{font-size:13px;margin:2px 0 0 2px}
.escalon .paso{font-size:12px;color:var(--suave);margin:3px 0 0 8px}
details.doc{background:var(--tarjeta);border:1px solid var(--borde);border-radius:12px;
padding:10px 12px;margin-bottom:8px}
details.doc[open]{border-color:var(--acento)}
details.doc summary{cursor:pointer;font-weight:600;font-size:15px}
details.doc summary small{display:block;font-weight:400;font-size:11px;color:var(--suave)}
.md{font-size:14px;line-height:1.55;overflow-wrap:anywhere}
.md h2,.md h3,.md h4,.md h5,.md h6{font-size:15px;margin:14px 0 4px}
.md ul,.md ol{padding-left:20px;margin:6px 0}
.md li{margin:3px 0}
.md blockquote{margin:8px 0;padding:6px 10px;border-left:3px solid var(--acento);
background:#faf3f5;color:var(--texto)}
.md pre{white-space:pre-wrap;background:#f4f1f0;border-radius:8px;padding:8px;
font-size:12px}
.md code{background:#f4f1f0;border-radius:4px;padding:0 4px;font-size:12px}
.md hr{border:0;border-top:1px solid var(--borde);margin:12px 0}
table.md,table.datos{border-collapse:collapse;font-size:13px;min-width:100%}
table.md th,table.md td,table.datos th,table.datos td{border-bottom:1px solid
var(--borde);padding:5px 6px;text-align:left;vertical-align:top}
table.datos td.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.md table th,.md table td{overflow-wrap:normal;word-break:normal;min-width:5.5em}
.md table td b{white-space:nowrap}
table.datos th{white-space:nowrap}
.ind{display:flex;gap:8px;padding:7px 0;border-bottom:1px solid var(--borde);
font-size:14px}
.ind:last-child{border-bottom:0}
.ind small{display:block;color:var(--suave);font-size:12px}
.ind .como{font-size:12px;margin-top:3px;color:#7a5a12}
.ind.no{opacity:.92}
.siguiente{text-align:right;margin:18px 0 0}
.siguiente a{font-weight:600}
"""

#: Lo único de JavaScript de esta página: el botón «Copiar» de las plantillas y
#: las casillas de los pasos (se guardan solo en este celular, `localStorage`;
#: si el navegador no deja, funcionan igual y no se recuerdan).
_JS_COPIAR = """
<script>
document.querySelectorAll('button.copiar').forEach(b=>b.addEventListener('click',
async()=>{const t=b.parentElement.querySelector('pre').innerText;
try{await navigator.clipboard.writeText(t)}catch(e){const a=document.createElement(
'textarea');a.value=t;document.body.appendChild(a);a.select();
document.execCommand('copy');a.remove()}
const antes=b.textContent;b.textContent='¡Copiado! ✓';
setTimeout(()=>{b.textContent=antes},1800)}));
function avance(t){const c=[...t.querySelectorAll('input[data-paso]')],
a=t.querySelector('.chip.avance');if(!a||!c.length)return;
const n=c.filter(x=>x.checked).length;a.textContent=n+'/'+c.length+' pasos';
a.classList.toggle('completa',n===c.length)}
document.querySelectorAll('details.tarea').forEach(t=>{
 t.querySelectorAll('input[data-paso]').forEach(x=>{const k='mk-paso-'+x.dataset.paso;
  try{x.checked=localStorage.getItem(k)==='1'}catch(e){}
  x.addEventListener('change',()=>{try{x.checked?localStorage.setItem(k,'1')
  :localStorage.removeItem(k)}catch(e){}avance(t)})});avance(t)});
</script>
"""


# ---------------------------------------------------------------------------
# Ayudantes: todo texto que viene del archivo pasa por `_t` (escapado).
# ---------------------------------------------------------------------------


def _t(valor) -> str:
    return html.escape(str(valor if valor is not None else ""))


def _lista(datos: dict, clave: str) -> list[dict]:
    return [x for x in datos.get(clave) or [] if isinstance(x, dict)]


def _etiqueta(tabla: dict[str, str], valor) -> str:
    valor = str(valor or "")
    return tabla.get(valor, valor.replace("_", " ").capitalize())


def _chip(tabla: dict[str, str], valor) -> str:
    if not valor:
        return ""
    clase = html.escape(str(valor), quote=True)
    return f"<span class='chip {clase}'>{_t(_etiqueta(tabla, valor))}</span>"


def _fecha(valor) -> str:
    """«2026-10-02» -> «2 oct 2026»; lo que no sea fecha, tal cual."""
    try:
        d = date.fromisoformat(str(valor))
    except ValueError:
        return _t(valor)
    return f"{d.day} {_MESES[d.month - 1]} {d.year}"


def _pesos(valor) -> str:
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        return _t(valor)
    if valor < 0:
        return "-" + formatear_cop(round(-valor))
    return formatear_cop(round(valor))


def _numero(valor) -> str:
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        return _t(valor)
    return f"{round(valor):,}".replace(",", ".")


def _parrafo(clase: str, texto) -> str:
    return f"<p class={clase}>{_t(texto)}</p>" if texto else ""


# ---------------------------------------------------------------------------
# Las secciones, en el orden del formato (§3.3 de PARA-EL-PANEL.md).
# Cada una devuelve "" si no hay nada que mostrar.
# ---------------------------------------------------------------------------


def _seccion_alertas(d: dict) -> str:
    partes = [
        f"<div class='alerta {'urgente' if a.get('nivel') == 'urgente' else 'aviso'}'>"
        f"<b>{'🚨' if a.get('nivel') == 'urgente' else '⚠️'} {_t(a.get('titulo'))}</b>"
        f"{_t(a.get('detalle'))}</div>"
        for a in _lista(d, "alertas")
    ]
    return f"<section id=alertas>{''.join(partes)}</section>" if partes else ""


def _casilla(tarea: str, texto) -> str:
    """Un paso como casilla. La marca vive SOLO en el celular de quien la toca
    (es su lista de la receta, no contenido de marketing): se guarda por la
    tarea y el texto del paso, así que sobrevive a una revisión nueva si el
    paso no cambió."""
    clave = hashlib.sha1(f"{tarea}|{texto}".encode(), usedforsecurity=False).hexdigest()
    return (
        f"<label class=casilla><input type=checkbox data-paso='{clave[:12]}'>"
        f"<span>{_t(texto)}</span></label>"
    )


def _seccion_tareas(d: dict) -> str:
    tareas = _lista(d, "tareas")
    if not tareas:
        return ""
    cerradas = ("hecho", "descartado")
    # La única excepción al orden que pide el formato: lo hecho, al final.
    orden = [t for t in tareas if t.get("estado") not in cerradas] + [
        t for t in tareas if t.get("estado") in cerradas
    ]
    abiertas = sum(1 for t in tareas if t.get("estado") not in cerradas)
    partes = [
        f"<section><h2 id=tareas>Qué hacer <span class=cuenta>{abiertas}</span></h2>"
        "<p class=ayuda>En orden de importancia. Toca una tarea para abrirla y ve "
        "marcando los pasos (las marcas quedan en este celular). Cuando la termines, "
        "cuéntaselo a Camilo: en la próxima revisión llega como hecha.</p>"
    ]
    for i, t in enumerate(orden):
        estado = str(t.get("estado") or "")
        ident = str(t.get("id") or i)
        pasos = []
        for p in t.get("pasos") or []:
            if isinstance(p, str):
                p = {"texto": p}
            if not isinstance(p, dict):
                continue
            sub = "".join(
                f"<li>{_casilla(ident, s)}</li>" for s in p.get("subpasos") or []
            )
            pasos.append(
                f"<li>{_casilla(ident, p.get('texto'))}"
                f"{f'<ul>{sub}</ul>' if sub else ''}</li>"
            )
        plantillas = "".join(
            "<div class=plantilla>"
            f"<div class=etiqueta>{_t(pl.get('etiqueta'))}</div>"
            f"<pre>{_t(pl.get('texto'))}</pre>"
            "<button type=button class=copiar>📋 Copiar</button></div>"
            for pl in t.get("plantillas") or []
            if isinstance(pl, dict) and pl.get("texto")
        )
        quien = (
            f"<span class=chip>👤 {_t(_etiqueta(QUIEN, t.get('quien')))}</span>"
            if t.get("quien")
            else ""
        )
        # Abierta de entrada solo la primera pendiente: lo que toca ahora.
        abierta = " open" if i == 0 and estado not in cerradas else ""
        partes.append(
            f"<details class='tarea {html.escape(estado, quote=True)}' "
            f"id='{html.escape(ident, quote=True)}'{abierta}><summary>"
            f"<div><span class=num>{_t(t.get('id'))}</span>"
            f"<b>{_t(t.get('titulo'))}</b></div>"
            "<div class=chips>"
            + _chip(CUANDO, t.get("cuando"))
            + quien
            + _chip(ESTADO_TAREA, estado)
            + ("<span class='chip avance'></span>" if pasos else "")
            + "</div></summary>"
            + _parrafo("porque", t.get("por_que"))
            + (f"<ol class=pasos>{''.join(pasos)}</ol>" if pasos else "")
            + plantillas
            + _parrafo("nota", t.get("nota"))
            + "</details>"
        )
    partes.append("</section>")
    return "".join(partes)


def _tono(x: dict) -> str:
    return x["tono"] if x.get("tono") in ("bueno", "malo") else "neutro"


def _seccion_reglas_semanales(d: dict) -> str:
    r = d.get("reglas_semanales")
    if not isinstance(r, dict):
        return ""
    reglas = [x for x in r.get("reglas") or [] if isinstance(x, dict)]
    filas = "".join(
        f"<div class='regla {_tono(x)}'>"
        f"<div class=si>{_t(x.get('si'))}</div>"
        f"<div class=hacer>→ {_t(x.get('hacer'))}</div></div>"
        for x in reglas
    )
    if not filas and not r.get("formula"):
        return ""
    return (
        f"<section><h2 id=reglas>{_t(r.get('titulo') or 'Reglas de cada lunes')}</h2>"
        "<article>"
        + (f"<p class=formula>{_t(r.get('formula'))}</p>" if r.get("formula") else "")
        + _parrafo("nota", r.get("ejemplo"))
        + (f"<div class=semaforo>{filas}</div>" if filas else "")
        + "</article></section>"
    )


def _seccion_datos_que_faltan(d: dict) -> str:
    datos = [x for x in d.get("datos_que_faltan") or [] if x]
    if not datos:
        return ""
    items = "".join(f"<li>{_t(x)}</li>" for x in datos)
    return (
        "<section><h2 id=faltan>Lo que hace falta saber</h2><article>"
        "<p class=ayuda>Para afinar la pauta. Si sabes alguna, cuéntasela a "
        f"Camilo.</p><ol class=pasos>{items}</ol></article></section>"
    )


def _seccion_cifras(d: dict) -> str:
    cifras = _lista(d, "cifras")
    if not cifras:
        return ""
    fichas = []
    for c in cifras:
        unidad = c.get("unidad")
        valor = c.get("valor")
        texto = (
            _pesos(valor)
            if unidad == "cop"
            else _numero(valor)
            if unidad == "numero"
            else _t(valor)
        )
        tono = c.get("tono") if c.get("tono") in ("bueno", "malo") else "neutro"
        fichas.append(
            f"<div class='cifra {tono}'><div class=etiqueta>{_t(c.get('etiqueta'))}</div>"
            f"<div class=valor>{texto}</div>{_parrafo('nota', c.get('nota'))}</div>"
        )
    return (
        "<section><h2 id=numeros>Cómo vamos</h2>"
        f"<div class=cifras>{''.join(fichas)}</div></section>"
    )


def _mes(valor) -> str:
    """«2026-01» (o 202601, como el ERP) -> «ene 2026»; lo que no sea mes, tal cual."""
    texto = str(valor or "").removesuffix(".0")
    if len(texto) == 6 and texto.isdigit():
        texto = f"{texto[:4]}-{texto[4:]}"
    try:
        anio, mes = texto.split("-")
        return f"{_MESES[int(mes) - 1]} {int(anio)}"
    except (ValueError, IndexError):
        return _t(texto)


def _seccion_rentabilidad(d: dict) -> str:
    r = d.get("rentabilidad")
    if not isinstance(r, dict):
        return ""
    meses = [m for m in r.get("meses") or [] if isinstance(m, dict)]
    total = r.get("total") if isinstance(r.get("total"), dict) else None
    if not meses and not total:
        return ""
    base = [
        (etiqueta, r.get(clave))
        for etiqueta, clave in (
            ("Se vende en", "ticket_promedio_cop"),
            ("Cuesta hacerlo", "costo_por_anillo_cop"),
            ("Queda por anillo", "ganancia_por_anillo_cop"),
        )
        if r.get(clave) is not None
    ]
    cabeza = "".join(f"<span class=chip>{e}: <b>{_pesos(v)}</b></span>" for e, v in base)

    def fila(m: dict, clase: str) -> str:
        return (
            f"<tr class='{clase}'><td>{_mes(m.get('mes'))}</td>"
            f"<td class=ganancia>{_pesos(m.get('ganancia_cop'))}</td>"
            f"<td>{_numero(m.get('anillos'))}</td>"
            f"<td>{_pesos(m.get('costo_por_venta_cop'))}</td>"
            f"<td>{_pesos(m.get('pauta_cop'))}</td>"
            f"<td>{_pesos(m.get('ventas_cop'))}</td></tr>"
        )

    def grupo(m: dict) -> str:
        return "g-" + html.escape(str(m.get("grupo") or ""), quote=True)

    filas = "".join(fila(m, grupo(m)) for m in meses)
    if total:
        filas += fila(total, "total")
    grupos = sorted({str(m.get("grupo")) for m in meses if m.get("grupo")})
    leyenda = (
        "<div class=leyenda>"
        + "".join(
            f"<span><i class='g-{html.escape(g, quote=True)}'></i>Pauta {_t(g)}</span>"
            for g in grupos
        )
        + "</div>"
        if grupos
        else ""
    )
    return (
        "<section><h2 id=rentabilidad>La ganancia, mes a mes</h2><article>"
        + (f"<div class=chips>{cabeza}</div>" if cabeza else "")
        + leyenda
        + "<div class=desliza><table class='tabla rentabilidad'>"
        "<tr><th>Mes</th><th class=ganancia>Ganancia</th><th>Anillos</th>"
        "<th>Cada venta costó</th><th>Pauta</th><th>Ventas</th></tr>"
        + filas
        + "</table></div>"
        + _parrafo("nota", r.get("nota"))
        + "</article></section>"
    )


def _n(x) -> float:
    """Un número de la foto del ERP; lo que falta o no es número, 0."""
    return num.numero(x) or 0.0


def _rentabilidad(ctx: Contexto) -> str:
    """La ganancia mes a mes: la del ERP si hay foto (02/10: «conecta el marketing
    con el costo que calculaste»); si no, la que trae la carpeta de marketing."""
    f = ctx.foto_erp or {}
    meses = [
        m for m in f.get("mensual", []) if isinstance(m, dict) and _n(m.get("Unidades"))
    ]
    if not meses:
        return _seccion_rentabilidad(ctx.d)
    piezas = sum(_n(m.get("Unidades")) for m in meses)
    ventas = sum(_n(m.get("Ingresos")) for m in meses)
    ticket = ventas / piezas if piezas else 0
    real = _n(f.get("costo_real"))
    chips = [("Se vende en (promedio)", ticket)]
    if real:
        chips += [("Cuesta hacerlo hoy (ERP)", real), ("Queda por pieza", ticket - real)]
    cabeza = "".join(f"<span class=chip>{e}: <b>{_pesos(v)}</b></span>" for e, v in chips)

    def fila(m: dict, clase: str = "") -> str:
        n = _n(m.get("Unidades"))
        costo = _n(m.get("COGS_Std")) + _n(m.get("Gastos")) + _n(m.get("Deprec"))
        pauta = _n(m.get("Publicidad"))
        util = _n(m.get("Utilidad_Op"))
        return (
            f"<tr class='{clase or ('g-moderada' if util >= 0 else 'g-alta')}'>"
            f"<td>{_mes(m.get('MesKey'))}</td>"
            f"<td class=ganancia>{_pesos(util)}</td>"
            f"<td>{_numero(n)}</td>"
            f"<td>{_pesos(costo / n) if n else ''}</td>"
            f"<td>{_pesos(pauta / n) if n else ''}</td>"
            f"<td>{_pesos(pauta)}</td>"
            f"<td>{_pesos(_n(m.get('Ingresos')))}</td></tr>"
        )

    total = {
        "MesKey": "Total",
        **{
            k: sum(_n(m.get(k)) for m in meses)
            for k in (
                "Unidades",
                "COGS_Std",
                "Gastos",
                "Deprec",
                "Publicidad",
                "Utilidad_Op",
                "Ingresos",
            )
        },
    }
    return (
        "<section><h2 id=rentabilidad>La ganancia, mes a mes (del ERP)</h2><article>"
        f"<div class=chips>{cabeza}</div>"
        "<div class=desliza><table class='tabla rentabilidad'>"
        "<tr><th>Mes</th><th class=ganancia>Ganancia</th><th>Piezas</th>"
        "<th>Costo por pieza</th><th>Cada venta costó (pauta)</th><th>Pauta</th>"
        "<th>Ventas</th></tr>"
        + "".join(fila(m) for m in meses)
        + fila(total, "total")
        + "</table></div>"
        "<p class=nota>Ganancia = lo que quedó después de TODO (costo de lo vendido con "
        "la plata de cada mes, publicidad, salario de Lía, taller, familia, "
        "diligencias, colchón y equipos). Costo por pieza = todo eso menos la "
        f"publicidad, ÷ piezas. Detalle en <a href='/panel/finanzas?token={_t(ctx.token)}"
        "&vista=resultados'>Finanzas → Resultados</a>.</p>"
        "</article></section>"
    )


#: Colores de las barras por grupo, en orden de aparición del grupo.
_COLORES_BARRA = ("#6f9e7f", "#c96f5b", "#7d8fc4", "#c9a24f", "#9a7fc0")


def _una_grafica(g: dict) -> str:
    serie = [p for p in g.get("serie") or [] if isinstance(p, dict)]
    valores = [
        p.get("valor")
        for p in serie
        if isinstance(p.get("valor"), int | float)
        and not isinstance(p.get("valor"), bool)
    ]
    if not valores:
        return ""
    tope = max(max(valores), 1)
    grupos = g.get("grupos") if isinstance(g.get("grupos"), dict) else {}
    orden_grupos = list(grupos) + [
        p.get("grupo") for p in serie if p.get("grupo") and p.get("grupo") not in grupos
    ]
    color = {
        k: _COLORES_BARRA[i % len(_COLORES_BARRA)] for i, k in enumerate(orden_grupos)
    }
    formato = _pesos if g.get("unidad") == "cop" else _numero
    filas = []
    for p in serie:
        v = p.get("valor")
        if isinstance(v, bool) or not isinstance(v, int | float):
            continue
        filas.append(
            f"<div class=barra><span>{_t(p.get('etiqueta'))}</span>"
            f"<span class=fondo><span class=lleno style='display:block;"
            f"width:{max(v / tope * 100, 1):.1f}%;"
            f"background:{color.get(p.get('grupo'), '#b9a6a0')}'></span></span>"
            f"<span class=cuanto>{formato(v)}</span></div>"
        )
    leyenda = "".join(
        f"<span><i style='background:{color[k]}'></i>{_t(grupos.get(k, k))}</span>"
        for k in orden_grupos
    )
    return (
        f"<article><b>{_t(g.get('titulo'))}</b>"
        + (f"<div class=leyenda>{leyenda}</div>" if leyenda else "")
        + f"<div class=barras>{''.join(filas)}</div>"
        + _parrafo("fuente", g.get("fuente"))
        + "</article>"
    )


def _seccion_indicadores(d: dict) -> str:
    graficas = [_una_grafica(g) for g in _lista(d, "indicadores")]
    graficas = [g for g in graficas if g]
    if not graficas:
        return ""
    return f"<section><h2 id=graficas>Mes a mes</h2>{''.join(graficas)}</section>"


def _seccion_diagnostico(d: dict) -> str:
    items = _lista(d, "diagnostico")
    if not items:
        return ""
    partes = [
        f"<article class='{'principal' if x.get('principal') else ''}'>"
        f"<b>{'⭐ ' if x.get('principal') else ''}{_t(x.get('titulo'))}</b>"
        f"<p class=dato-par>{_t(x.get('detalle'))}</p></article>"
        for x in items
    ]
    return f"<section><h2 id=diagnostico>Qué está pasando</h2>{''.join(partes)}</section>"


def _seccion_costo_por_venta(d: dict) -> str:
    cpv = d.get("costo_por_venta")
    if not isinstance(cpv, dict):
        return ""
    columnas = cpv.get("columnas") or []
    filas = [f for f in cpv.get("filas") or [] if isinstance(f, dict)]
    if not columnas or not filas:
        return ""
    cabeza = "".join(f"<th>a {_pesos(c)} por conversación</th>" for c in columnas)
    cuerpo = "".join(
        f"<tr><td>{_t(f.get('compra'))}</td>"
        + "".join(f"<td>{_pesos(v)}</td>" for v in f.get("valores_cop") or [])
        + "</tr>"
        for f in filas
    )
    return (
        f"<section><h2 id=costo-venta>{_t(cpv.get('titulo') or 'Costo por venta')}</h2>"
        "<article><table class=tabla>"
        f"<tr><th>Si compra…</th>{cabeza}</tr>{cuerpo}</table>"
        f"{_parrafo('nota', cpv.get('nota'))}</article></section>"
    )


def _seccion_pruebas(d: dict) -> str:
    pruebas = _lista(d, "pruebas")
    if not pruebas:
        return ""
    partes = []
    for p in pruebas:
        fechas = " → ".join(_fecha(f) for f in (p.get("inicio"), p.get("fin")) if f)
        partes.append(
            f"<article><div><span class=num>{_t(p.get('id'))}</span>"
            f"<b>{_t(p.get('pregunta'))}</b></div>"
            f"<div class=chips>{_chip(ESTADO_PRUEBA, p.get('estado'))}"
            + (f"<span class=chip>📅 {fechas}</span>" if fechas else "")
            + "</div>"
            + (
                f"<p class=dato-par><b>Éxito si:</b> {_t(p.get('exito'))}</p>"
                if p.get("exito")
                else ""
            )
            + (
                f"<p class=dato-par><b>Resultado:</b> {_t(p.get('resultado'))}</p>"
                if p.get("resultado")
                else ""
            )
            + "</article>"
        )
    return (
        "<section><h2 id=pruebas>Las pruebas</h2>"
        "<p class=ayuda>Un cambio a la vez, y se juzga a los 7 días.</p>"
        f"{''.join(partes)}</section>"
    )


def _seccion_reels(d: dict) -> str:
    reels = _lista(d, "reels")
    if not reels:
        return ""
    partes = []
    for r in reels:
        datos = []
        if r.get("vistas") is not None:
            datos.append(f"👁 {_numero(r.get('vistas'))} vistas")
        if r.get("publicado"):
            datos.append(f"📅 {_fecha(r.get('publicado'))}")
        if r.get("gasto_cop") is not None:
            datos.append(f"💸 {_pesos(r.get('gasto_cop'))} en pauta")
        costo = ""
        if r.get("costo_mes_1_cop") is not None:
            costo = (
                f"Arrancó en <b>{_pesos(r.get('costo_mes_1_cop'))}</b> por conversación"
            )
            if r.get("costo_actual_cop") is not None:
                costo += f" → hoy <b>{_pesos(r.get('costo_actual_cop'))}</b>"
        url = str(r.get("url") or "")
        enlace = (
            f"<a class=fuera href='{html.escape(url, quote=True)}' target=_blank "
            "rel='noopener noreferrer'>Ver en Instagram ↗</a>"
            if url.startswith("https://")
            else ""
        )
        partes.append(
            f"<article><b>{_t(r.get('nombre'))}</b>"
            f"<div class=chips>{_chip(ESTADO_REEL, r.get('estado'))}"
            + "".join(f"<span class=chip>{x}</span>" for x in datos)
            + "</div>"
            + _parrafo("dato-par", r.get("descripcion"))
            + (f"<p class=dato-par>{costo}</p>" if costo else "")
            + enlace
            + "</article>"
        )
    return f"<section><h2 id=reels>Los videos</h2>{''.join(partes)}</section>"


def _seccion_perfil(d: dict) -> str:
    partes = [
        f"<article><b>{_t(x.get('parte'))}</b>"
        f"<p class=dato-par><b>Hoy:</b> {_t(x.get('hoy'))}</p>"
        f"<p class=dato-par><b>Cambiar:</b> {_t(x.get('cambiar'))}</p></article>"
        for x in _lista(d, "perfil")
    ]
    if not partes:
        return ""
    return (
        f"<section><h2 id=perfil>El perfil de Instagram</h2>{''.join(partes)}</section>"
    )


def _seccion_formula(d: dict) -> str:
    f = d.get("formula")
    if not isinstance(f, dict) or not f.get("pasos"):
        return ""
    pasos = "".join(f"<li>{_t(p)}</li>" for p in f.get("pasos") or [])
    return (
        f"<section><h2 id=formula>{_t(f.get('titulo') or 'La fórmula')}</h2><article>"
        f"<ol class=pasos>{pasos}</ol>{_parrafo('nota', f.get('variaciones'))}"
        "</article></section>"
    )


def _seccion_angulos(d: dict) -> str:
    partes = [
        f"<article><b>{_t(x.get('angulo'))}</b>"
        f"<p class=dato-par><b>Para:</b> {_t(x.get('para_quien'))}</p>"
        f"<p class=dato-par><b>Empieza:</b> {_t(x.get('como_empieza'))}</p></article>"
        for x in _lista(d, "angulos")
    ]
    if not partes:
        return ""
    return (
        "<section><h2 id=angulos>Ideas para videos nuevos</h2>"
        f"{''.join(partes)}</section>"
    )


def _seccion_fechas(d: dict, hoy: date, solo_proximas: bool = False) -> str:
    fechas = _lista(d, "fechas")
    if not fechas:
        return ""

    def cuando(x: dict) -> date:
        try:
            return date.fromisoformat(str(x.get("fecha")))
        except ValueError:
            return date.max

    fechas.sort(key=cuando)
    items = []
    for x in fechas:
        faltan = (cuando(x) - hoy).days if cuando(x) != date.max else None
        clases = []
        if x.get("clave"):
            clases.append("clave")
        if faltan is not None and faltan < 0:
            clases.append("pasada")
        # Lo de los próximos 7 días, resaltado y con cuánto falta.
        pronto = ""
        if faltan is not None and 0 <= faltan <= 7:
            clases.append("proxima")
            pronto = {0: "hoy", 1: "mañana"}.get(faltan, f"en {faltan} días")
        elif solo_proximas:
            continue
        items.append(
            f"<li class='{' '.join(clases)}'><span class=dia>{_fecha(x.get('fecha'))}"
            f"</span><span>{'⭐ ' if x.get('clave') else ''}{_t(x.get('texto'))}"
            f"{f' · <b>{pronto}</b>' if pronto else ''}</span></li>"
        )
    if not items:
        return ""
    titulo = "Lo de los próximos 7 días" if solo_proximas else "El calendario"
    return (
        f"<section><h2 id=fechas>{titulo}</h2><article>"
        f"<ul class=fechas>{''.join(items)}</ul></article></section>"
    )


def _seccion_aprendizajes(d: dict) -> str:
    partes = [
        f"<article><b>{_t(x.get('texto'))}</b>"
        f"<div class=chips>{_chip(CONFIANZA, x.get('confianza'))}</div>"
        + _parrafo("dato-par", x.get("evidencia"))
        + "</article>"
        for x in _lista(d, "aprendizajes")
    ]
    if not partes:
        return ""
    return (
        f"<section><h2 id=aprendizajes>Lo que ya sabemos</h2>{''.join(partes)}</section>"
    )


# ---------------------------------------------------------------------------
# La carpeta entera (01/10): documentos y tablas, además del tablero
# ---------------------------------------------------------------------------


@dataclass
class Carpeta:
    """Lo que hay en el servidor de la carpeta de marketing."""

    tablero: Tablero | None = None
    problema: str = ""
    docs: dict[str, str] = field(default_factory=dict)  # ruta → texto .md
    tablas: dict[str, str] = field(default_factory=dict)  # ruta → texto .csv

    def doc(self, ruta: str) -> str:
        return self.docs.get(ruta, "")

    def tabla(self, ruta: str) -> str:
        return self.tablas.get(ruta, "")


def leer_carpeta(carpeta: Path) -> Carpeta:
    """El tablero y todo lo demás. Nunca lanza: lo que falla se cuenta."""
    c = Carpeta()
    c.tablero, c.problema = leer(carpeta / "PARA-EL-PANEL.md")
    if carpeta.is_dir():
        for p in sorted(carpeta.rglob("*")):
            if not p.is_file() or p.name == "PARA-EL-PANEL.md":
                continue
            ruta = p.relative_to(carpeta).as_posix()
            try:
                texto = p.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError) as exc:
                log.warning("marketing: no se pudo leer %s (%s)", ruta, exc)
                continue
            if ruta.endswith(".md"):
                c.docs[ruta] = texto
            elif ruta.endswith(".csv"):
                c.tablas[ruta] = texto
    return c


@dataclass
class Contexto:
    """Lo que necesita cada sección para dibujarse."""

    d: dict
    hoy: date
    carpeta: Carpeta
    meses: list = field(default_factory=list)
    #: La revisión del estándar sobre lo que está subido (qué sirve y qué no).
    informe: estandar.Informe | None = None
    #: Lo que vende el bot (sus pedidos); None si no se pasó.
    bot: num.VentasDelBot | None = None
    #: La foto del ERP (ver `app/adapters/erp/marketing.py`).
    foto_erp: dict | None = None
    ventas_de_prueba: bool = True
    token: str = ""
    #: El embudo del chat día por día (`tablero.embudo_por_dia`), para «Piloto».
    embudo_bot: list[dict] | None = None
    #: Los filtros de «Piloto»: campana, fase, por, plan (y anio, mes).
    piloto: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# El período (02/10): «en todos los apartados del panel, filtros de fechas»
# ---------------------------------------------------------------------------

_NOMBRES_MES = (
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
#: Las columnas que dicen de cuándo es una fila (AAAA-MM o AAAA-MM-DD).
_COLUMNAS_DE_FECHA = ("mes", "fecha", "semana")


def _prefijo(anio: int | None, mes: int | None) -> str:
    if anio is None:
        return ""
    return f"{anio}-{mes:02d}" if mes else str(anio)


def _del_periodo(texto: str, prefijo: str) -> str:
    """Solo las filas del año o del mes escogido. Una tabla sin columna de
    fecha (creativos) va entera; el renglón TOTAL sale (era de todo)."""
    if not prefijo or not texto.strip():
        return texto
    filas = list(csv.reader(io.StringIO(texto)))
    cabeza = [c.strip().lower() for c in filas[0]] if filas else []
    col = next((cabeza.index(c) for c in _COLUMNAS_DE_FECHA if c in cabeza), None)
    if col is None:
        return texto
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(filas[0])
    for fila in filas[1:]:
        if len(fila) > col and fila[col].strip().startswith(prefijo):
            escritor.writerow(fila)
    return salida.getvalue()


def _carpeta_del_periodo(c: Carpeta, prefijo: str) -> Carpeta:
    if not prefijo:
        return c
    return Carpeta(
        tablero=c.tablero,
        problema=c.problema,
        docs=c.docs,
        tablas={ruta: _del_periodo(texto, prefijo) for ruta, texto in c.tablas.items()},
    )


def _foto_del_periodo(foto: dict | None, prefijo: str) -> dict | None:
    if not foto or not prefijo:
        return foto
    clave = prefijo.replace("-", "")
    return {
        **foto,
        "mensual": [
            m
            for m in foto.get("mensual") or []
            if str(m.get("MesKey") or m.get("mes") or "").startswith(clave)
        ],
    }


def _meses_con_datos(c: Carpeta) -> list[str]:
    """«2026-09»… de las tablas de ventas y de Meta (las que tienen historia)."""
    meses = set()
    for ruta in ("datos/ventas_mensuales.csv", "datos/meta_mensual.csv"):
        for fila in csv.DictReader(io.StringIO(c.tabla(ruta))):
            valor = str(fila.get("mes") or "").strip()
            if len(valor) == 7 and valor[:4].isdigit() and valor[5:].isdigit():
                meses.add(valor)
    return sorted(meses)


def _selector(
    tok: str, vista: str, meses: list[str], anio: int | None, mes: int | None
) -> str:
    anios = sorted({int(m[:4]) for m in meses}, reverse=True)
    opciones_anio = "<option value=''>Todos los años</option>" + "".join(
        f"<option value={a}{' selected' if a == anio else ''}>{a}</option>" for a in anios
    )
    del_anio = sorted({int(m[5:]) for m in meses if anio and m.startswith(str(anio))})
    opciones_mes = "<option value=''>Todo el año</option>" + "".join(
        f"<option value={m}{' selected' if m == mes else ''}>{_NOMBRES_MES[m - 1]}"
        "</option>"
        for m in del_anio
    )
    viendo = (
        "todo el historial"
        if anio is None
        else (f"{_NOMBRES_MES[mes - 1]} {anio}" if mes else f"todo {anio}")
    )
    return (
        "<form method=get action='/panel/marketing' class=periodo>"
        f"<input type=hidden name=token value='{tok}'>"
        f"<input type=hidden name=vista value='{vista}'>"
        f"<label>Período <select name=anio onchange='this.form.submit()'>"
        f"{opciones_anio}</select></label> <select name=mes "
        f"onchange='this.form.submit()'>{opciones_mes}</select> <button>Ver</button>"
        f"<span class=ayuda>Viendo: <b>{viendo}</b> · cambia las tablas y lo "
        "calculado; lo que escribió el marketing va igual</span></form>"
    )


def _contexto(
    carpeta: Carpeta,
    hoy: date,
    bot_filas: list[dict] | None = None,
    reales_desde: str = "",
    foto_erp: dict | None = None,
    token: str = "",
) -> Contexto:
    d = carpeta.tablero.datos if carpeta.tablero else {}
    meses = num.meses(
        carpeta.tabla("datos/ventas_mensuales.csv"),
        carpeta.tabla("datos/meta_mensual.csv"),
    )
    archivos = {**carpeta.docs, **carpeta.tablas}
    informe = estandar.revisar(archivos, d if carpeta.tablero else None)
    bot = num.ventas_del_bot(bot_filas, reales_desde) if bot_filas is not None else None
    return Contexto(
        d,
        hoy,
        carpeta,
        meses,
        informe,
        bot,
        foto_erp,
        ventas_de_prueba=not reales_desde.strip(),
        token=html.escape(token),
    )


def _calculado(fuente: str) -> str:
    return f"<p class=fuente>🧮 Calculado por el panel con {_t(fuente)}.</p>"


# -- documentos ---------------------------------------------------------------


def _titulo_de(texto: str, ruta: str) -> str:
    for linea in texto.splitlines():
        if linea.startswith("# "):
            return linea[2:].strip()
    return ruta.rsplit("/", 1)[-1].removesuffix(".md").replace("-", " ").capitalize()


def _documento(ctx: Contexto, ruta: str, abierto: bool = False) -> str:
    texto = ctx.carpeta.doc(ruta)
    if not texto:
        return ""
    return (
        f"<details class=doc{' open' if abierto else ''}><summary>📄 "
        f"{_t(_titulo_de(texto, ruta))}<small>{_t(ruta)}</small></summary>"
        f"<div class=md>{md.a_html(texto)}</div></details>"
    )


def _documentos(ctx: Contexto, titulo: str, ancla: str, rutas: list[str]) -> str:
    partes = [x for x in (_documento(ctx, r) for r in rutas) if x]
    if not partes:
        return ""
    return f"<section><h2 id={ancla}>{titulo}</h2>{''.join(partes)}</section>"


# -- tablas ------------------------------------------------------------------

_NOMBRES_DE_COLUMNA = {
    "mes": "Mes",
    "gasto_cop": "Gasto",
    "gasto_pauta_cop": "Pauta",
    "ingresos_cop": "Ventas",
    "anillos_vendidos": "Anillos",
    "impresiones": "Impresiones",
    "alcance": "Alcance",
    "frecuencia": "Frecuencia",
    "cpm_cop": "CPM",
    "conversaciones_iniciadas": "Conversaciones",
    "conversaciones": "Conversaciones",
    "costo_por_conversacion_cop": "$/conversación",
    "tasa_cierre_pct": "Cierre %",
    "costo_por_venta_cop": "$/venta",
    "roas": "ROAS",
    "costo_anillos_cop": "Costo anillos",
    "ganancia_despues_de_pauta_cop": "Ganancia",
    "campana": "Campaña",
    "objetivo": "Objetivo",
    "anuncio": "Anuncio",
    "video": "Video",
}


def _objetivo(valor: str) -> str:
    """El objetivo de una campaña; «visitas al perfil» en rojo: no vende."""
    if "perfil" in valor.lower():
        return f"<span class='chip malo'>{_t(valor)}</span>"
    return _t(valor)


def _celda(columna: str, valor: str) -> str:
    n = num.numero(valor)
    if columna.endswith("_cop") and n is not None:
        return f"<td class=n>{_pesos(n)}</td>"
    if n is not None and columna not in ("mes", "publicado"):
        texto = f"{n:,.2f}".rstrip("0").rstrip(".") if n % 1 else f"{n:,.0f}"
        texto = texto.replace(",", "·").replace(".", ",").replace("·", ".")
        return f"<td class=n>{texto}</td>"
    if columna == "objetivo":
        return f"<td>{_objetivo(valor)}</td>"
    if valor.startswith("http"):
        return (
            f"<td><a href='{html.escape(valor, quote=True)}' target=_blank "
            "rel='noopener noreferrer'>abrir ↗</a></td>"
        )
    return f"<td>{md.en_linea(valor)}</td>"


def _tabla(texto_csv: str, columnas: list[str] | None = None, filas=None) -> str:
    filas = filas if filas is not None else num.leer_csv(texto_csv)
    if not filas:
        return ""
    columnas = columnas or list(filas[0])
    cabeza = "".join(
        f"<th>{_t(_NOMBRES_DE_COLUMNA.get(c, c.replace('_', ' ')))}</th>"
        for c in columnas
    )
    cuerpo = "".join(
        "<tr>" + "".join(_celda(c, f.get(c, "")) for c in columnas) + "</tr>"
        for f in filas
    )
    return (
        f"<div class=desliza><table class='tabla datos'><tr>{cabeza}</tr>{cuerpo}"
        "</table></div>"
    )


def _grafica_de(titulo: str, puntos: list[tuple[str, float]], unidad: str, fuente: str):
    """Una gráfica de barras con los mismos colores que las del tablero."""
    return _una_grafica(
        {
            "titulo": titulo,
            "unidad": unidad,
            "serie": [{"etiqueta": e, "valor": v} for e, v in puntos if v is not None],
            "fuente": fuente,
        }
    )


def _corto(clave: str) -> str:
    """«2026-09» -> «Sep 26»."""
    try:
        return f"{_MESES[int(clave[5:7]) - 1].capitalize()} {clave[2:4]}"
    except (ValueError, IndexError):
        return clave


# ---------------------------------------------------------------------------
# Las secciones nuevas (01/10)
# ---------------------------------------------------------------------------


def _formato_kpi(k) -> str:
    if k.valor is None:
        return "—"
    if k.unidad == "cop":
        return _pesos(k.valor)
    if k.unidad == "pct":
        return f"{k.valor:.1f} %".replace(".", ",")
    if k.unidad == "x":
        return f"{k.valor:.2f}×".replace(".", ",")
    if k.unidad == "decimal":
        return f"{k.valor:.2f}".replace(".", ",")
    return _numero(k.valor)


def _seccion_kpis(ctx: Contexto) -> str:
    ultimo, antes = num.ultimo_con_ventas(ctx.meses)
    if ultimo is None:
        return (
            "<section><h2 id=kpis>Indicadores del mes</h2><article><p class=ayuda>"
            "Todavía no hay tablas de datos (<code>datos/*.csv</code>) en la carpeta de "
            "marketing.</p></article></section>"
        )
    nombre_antes = num._nombre_mes(antes.mes) if antes else ""
    fichas = []
    for k in ultimo.kpis(antes):
        cambio = k.cambio_pct
        flecha = ""
        if cambio is not None and abs(cambio) >= 1:
            flecha = (
                f"<span class='delta {k.tono}'>{'▲' if cambio > 0 else '▼'} "
                f"{abs(cambio):.0f} %</span>"
            )
        fichas.append(
            f"<div class='kpi {k.tono}'><div class=etiqueta>{_t(k.nombre)}</div>"
            f"<div class=valor>{_formato_kpi(k)}</div>{flecha}"
            f"<div class=que>{_t(k.que_es)}</div></div>"
        )
    return (
        f"<section><h2 id=kpis>Indicadores de {_t(num._nombre_mes(ultimo.mes))}</h2>"
        + (
            f"<p class=ayuda>Las flechas comparan con {_t(nombre_antes)}: verde es "
            "mejor, rojo es peor.</p>"
            if antes
            else ""
        )
        + f"<div class=kpis>{''.join(fichas)}</div>"
        + _calculado("datos/ventas_mensuales.csv y datos/meta_mensual.csv")
        + "</section>"
    )


def _seccion_embudo(ctx: Contexto) -> str:
    ultimo, _ = num.ultimo_con_ventas(ctx.meses)
    if ultimo is None:
        return ""
    escalones = num.embudo(ultimo)
    if len(escalones) < 2:
        return ""
    tope = math.log10(max(e.cuantos for e in escalones) + 1)
    filas = "".join(
        f"<div class=escalon><div class=barra-embudo style='width:"
        f"{max(math.log10(e.cuantos + 1) / tope * 100, 12):.0f}%'>"
        f"<b>{_numero(e.cuantos)}</b></div><div class=nombre>{_t(e.nombre)}</div>"
        + (f"<div class=paso>↓ {_t(e.paso)}</div>" if e.paso else "")
        + "</div>"
        for e in escalones
    )
    return (
        f"<section><h2 id=embudo>El embudo de {_t(num._nombre_mes(ultimo.mes))}</h2>"
        f"<article>{filas}<p class=ayuda>Dónde se pierde la gente, de ver el anuncio a "
        "comprar. El ancho va en escala logarítmica para que quepan todos.</p>"
        + _calculado("datos/meta_mensual.csv y datos/ventas_mensuales.csv")
        + "</article></section>"
    )


def _seccion_graficas_de_tablas(ctx: Contexto) -> str:
    m = ctx.meses
    if not m:
        return ""
    fuente = "Ads Manager (datos/meta_mensual.csv)"
    graficas = [
        _grafica_de(
            "Pauta por mes, desde el principio",
            [(_corto(x.mes), x.pauta) for x in m],
            "cop",
            fuente,
        ),
        _grafica_de(
            "Conversaciones por mes",
            [(_corto(x.mes), x.conversaciones) for x in m],
            "numero",
            fuente,
        ),
        _grafica_de(
            "Costo por conversación",
            [(_corto(x.mes), x.costo_conversacion) for x in m],
            "cop",
            fuente,
        ),
        _grafica_de(
            "CPM (costo de 1.000 impresiones)",
            [(_corto(x.mes), x.cpm) for x in m],
            "cop",
            fuente,
        ),
        _grafica_de(
            "Personas alcanzadas",
            [(_corto(x.mes), x.alcance) for x in m],
            "numero",
            fuente,
        ),
    ]
    con_ventas = [x for x in m if x.anillos]
    if con_ventas:
        ventas = "Excel de Camilo (datos/ventas_mensuales.csv)"
        graficas += [
            _grafica_de(
                "Anillos vendidos",
                [(_corto(x.mes), x.anillos) for x in con_ventas],
                "numero",
                ventas,
            ),
            _grafica_de(
                "ROAS (pesos vendidos por peso de pauta)",
                [
                    (_corto(x.mes), round(x.ventas / x.pauta, 2))
                    for x in con_ventas
                    if x.ventas and x.pauta
                ],
                "numero",
                ventas,
            ),
            _grafica_de(
                "Tasa de cierre (de cada 100 que escriben)",
                [
                    (_corto(x.mes), round(x.anillos / x.conversaciones * 100, 2))
                    for x in con_ventas
                    if x.conversaciones
                ],
                "numero",
                ventas,
            ),
        ]
    graficas = [g for g in graficas if g]
    if not graficas:
        return ""
    return (
        "<section><h2 id=historia>La historia, mes a mes</h2>"
        + "".join(graficas)
        + "</section>"
    )


def _seccion_tablas_completas(ctx: Contexto) -> str:
    partes = []
    for ruta, titulo in (
        ("datos/ventas_mensuales.csv", "Ventas, pauta y ganancia por mes"),
        ("datos/meta_mensual.csv", "La cuenta de Meta, mes a mes"),
    ):
        tabla = _tabla(ctx.carpeta.tabla(ruta))
        if tabla:
            partes.append(
                f"<details class=doc><summary>📊 {titulo}<small>{ruta}</small></summary>"
                f"{tabla}</details>"
            )
    if not partes:
        return ""
    return f"<section><h2 id=tablas>Las tablas completas</h2>{''.join(partes)}</section>"


def _seccion_recomendaciones(ctx: Contexto, solo_importantes: bool = False) -> str:
    recs = num.recomendaciones(
        ctx.meses,
        ctx.carpeta.tabla("datos/meta_campanas_mensual.csv"),
        ctx.carpeta.tabla("datos/creativos.csv"),
        ctx.hoy,
        _ganancia_por_anillo(ctx),
    )
    if solo_importantes:
        recs = [r for r in recs if r.nivel != "bien"]
    if not recs:
        return ""
    iconos = {"urgente": "🚨", "aviso": "⚠️", "bien": "✅"}
    partes = "".join(
        f"<div class='alerta {r.nivel}'><b>{iconos.get(r.nivel, '•')} {_t(r.titulo)}</b>"
        f"{_t(r.detalle)}</div>"
        for r in recs
    )
    titulo = "Lo que muestran los números" if solo_importantes else "Recomendaciones"
    return (
        f"<section><h2 id=recomendaciones>{titulo}</h2>{partes}"
        + _calculado("las tablas de datos y los umbrales de las reglas de marketing")
        + "</section>"
    )


def _seccion_campanas(ctx: Contexto) -> str:
    filas = num.leer_csv(ctx.carpeta.tabla("datos/meta_campanas_mensual.csv"))
    if not filas:
        return ""
    # Por objetivo: dónde se fue la plata y qué trajo.
    objetivos: dict[str, list[float]] = {}
    for f in filas:
        g = objetivos.setdefault(f.get("objetivo") or "sin objetivo", [0.0, 0.0])
        g[0] += num.numero(f.get("gasto_cop")) or 0
        g[1] += num.numero(f.get("conversaciones_iniciadas")) or 0
    total = sum(g for g, _ in objetivos.values()) or 1
    resumen = "".join(
        f"<tr><td>{_objetivo(o)}</td><td class=n>{_pesos(g)}</td>"
        f"<td class=n>{g / total * 100:.0f} %</td><td class=n>{_numero(c)}</td>"
        f"<td class=n>{_pesos(g / c) if c else '—'}</td></tr>"
        for o, (g, c) in sorted(objetivos.items(), key=lambda x: -x[1][0])
    )
    por_mes: dict[str, list[dict]] = {}
    for f in filas:
        por_mes.setdefault(f.get("mes", ""), []).append(f)
    columnas = [
        "campana",
        "objetivo",
        "gasto_cop",
        "conversaciones_iniciadas",
        "costo_por_conversacion_cop",
        "alcance",
        "frecuencia",
        "cpm_cop",
    ]
    meses = []
    for i, mes in enumerate(sorted(por_mes, reverse=True)):
        meses.append(
            f"<details class=doc{' open' if i == 0 else ''}><summary>📅 "
            f"{_t(num._nombre_mes(mes))}<small>{len(por_mes[mes])} campaña(s)</small>"
            f"</summary>{_tabla('', columnas, por_mes[mes])}</details>"
        )
    return (
        "<section><h2 id=campanas>Las campañas</h2><article><b>Dónde se fue la plata, "
        "por "
        "objetivo (desde el principio)</b><div class=desliza><table class='tabla datos'>"
        "<tr><th>Objetivo</th><th>Gasto</th><th>%</th><th>Conversaciones</th>"
        f"<th>$/conversación</th></tr>{resumen}</table></div>"
        + _calculado("datos/meta_campanas_mensual.csv")
        + "</article>"
        + "".join(meses)
        + "</section>"
    )


def _seccion_anuncios(ctx: Contexto) -> str:
    filas = num.leer_csv(ctx.carpeta.tabla("datos/meta_anuncios_mensual.csv"))
    if not filas:
        return ""
    por_anuncio: dict[str, list[float]] = {}
    for f in filas:
        g = por_anuncio.setdefault(f.get("anuncio", "?"), [0.0, 0.0, 0.0])
        g[0] += num.numero(f.get("gasto_cop")) or 0
        g[1] += num.numero(f.get("conversaciones_iniciadas")) or 0
        g[2] += 1
    ranking = sorted(
        ((a, g, c, n) for a, (g, c, n) in por_anuncio.items() if c),
        key=lambda x: x[1] / x[2],
    )
    filas_html = "".join(
        f"<tr><td>{_t(a)}</td><td class=n>{_pesos(g / c)}</td><td "
        f"class=n>{_pesos(g)}</td>"
        f"<td class=n>{_numero(c)}</td><td class=n>{int(n)}</td></tr>"
        for a, g, c, n in ranking
    )
    columnas = [
        "mes",
        "anuncio",
        "video",
        "gasto_cop",
        "conversaciones_iniciadas",
        "costo_por_conversacion_cop",
        "frecuencia",
        "cpm_cop",
    ]
    detalle = sorted(filas, key=lambda f: f.get("mes", ""), reverse=True)
    return (
        "<section><h2 id=anuncios>Los anuncios</h2><article><b>Del más barato al más "
        "caro por conversación (todo el historial)</b><div class=desliza>"
        "<table class='tabla datos'><tr><th>Anuncio</th><th>$/conversación</th>"
        "<th>Gasto</th><th>Conversaciones</th><th>Meses</th></tr>"
        f"{filas_html}</table></div>"
        + _calculado("datos/meta_anuncios_mensual.csv")
        + "</article><details class=doc><summary>📊 Cada anuncio, mes a mes"
        "<small>datos/meta_anuncios_mensual.csv</small></summary>"
        + _tabla("", columnas, detalle)
        + "</details></section>"
    )


def _seccion_producciones(ctx: Contexto) -> str:
    texto = ctx.carpeta.tabla("datos/creativos.csv")
    if not texto:
        return ""
    columnas = [
        "nombre",
        "tipo",
        "publicado",
        "vistas_al_2026-09-30",
        "en_pauta",
        "gasto_total_cop",
        "costo_mes_1_cop",
        "costo_ultimo_mes_cop",
        "notas",
    ]
    filas = num.leer_csv(texto)
    columnas = [c for c in columnas if any(c in f for f in filas)] or None
    return (
        "<section><h2 id=producciones>Todas las producciones</h2>"
        "<p class=ayuda>Cada video o carrusel que se ha pautado: cuánto gastó, en cuánto "
        "arrancó la conversación y en cuánto terminó.</p>"
        f"{_tabla('', columnas, filas)}</section>"
    )


def _seccion_indicadores_pro(ctx: Contexto) -> str:
    ultimo, antes = num.ultimo_con_ventas(ctx.meses)
    valores = {k.clave: k for k in ultimo.kpis(antes)} if ultimo else {}
    extra = _extra_indicadores(ctx)
    por_area: dict[str, list[str]] = {}
    con_dato = 0
    for ind in num.CATALOGO:
        k = valores.get(ind.kpi) if ind.kpi else None
        if k is not None and k.valor is not None:
            con_dato += 1
            fila = (
                f"<div class='ind si'><span>✅</span><div><b>{_t(ind.nombre)}</b> · "
                f"{_formato_kpi(k)}<small>{_t(ind.que_es)}</small></div></div>"
            )
        elif ind.nombre in extra:
            con_dato += 1
            fila = (
                f"<div class='ind si'><span>✅</span><div><b>{_t(ind.nombre)}</b> · "
                f"{_t(extra[ind.nombre])}<small>{_t(ind.que_es)}</small></div></div>"
            )
        else:
            fila = (
                f"<div class='ind no'><span>⏳</span><div><b>{_t(ind.nombre)}</b>"
                f"<small>{_t(ind.que_es)}</small>"
                "<div class=como>Cómo tenerlo: "
                f"{_t(ind.como_conseguirlo)}</div></div></div>"
            )
        por_area.setdefault(ind.categoria, []).append(fila)
    areas = "".join(
        f"<article><b>{_t(area)}</b>{''.join(filas)}</article>"
        for area, filas in por_area.items()
    )
    return (
        "<section><h2 id=indicadores-pro>Todos los indicadores de un departamento de "
        f"marketing</h2><p class=ayuda><b>{con_dato} de {len(num.CATALOGO)}</b> ya "
        "tienen "
        "dato (✅). Los demás (⏳) dicen qué falta y cómo conseguirlo: es la lista de "
        "mejoras de medición, de la más importante a la menos en cada área.</p>"
        f"{areas}{_calculado('las tablas de datos de la carpeta de marketing')}</section>"
    )


def _extra_indicadores(ctx: Contexto) -> dict[str, str]:
    """Indicadores que salen de `datos/creativos.csv`."""
    filas = num.leer_csv(ctx.carpeta.tabla("datos/creativos.csv"))
    salida = {}
    propios = [
        f for f in filas if f.get("tipo", "").lower() in ("reel", "carrusel", "historia")
    ]
    fechas = []
    for f in propios:
        texto = f.get("publicado", "")
        try:
            fechas.append(date.fromisoformat(texto + "-01" if len(texto) == 7 else texto))
        except ValueError:
            continue
    if fechas:
        salida["Días del video más nuevo"] = f"{(ctx.hoy - max(fechas)).days} días"
    arranques = [num.numero(f.get("costo_mes_1_cop")) for f in filas]
    arranques = [a for a in arranques if a]
    if arranques:
        salida["Costo de arranque de cada producción"] = (
            f"el mejor, {_pesos(min(arranques))} por conversación"
        )
    salida.update(_extra_de_las_tablas(ctx))
    return salida


def _ultima(ctx: Contexto, archivo: str, orden: str = "mes") -> dict | None:
    filas = num.leer_csv(ctx.carpeta.tabla(f"datos/{archivo}"))
    return sorted(filas, key=lambda f: f.get(orden, ""))[-1] if filas else None


def _extra_de_las_tablas(ctx: Contexto) -> dict[str, str]:
    """Los indicadores que se llenan con las plantillas, el bot y el ERP."""
    salida: dict[str, str] = {}
    if (o := _ultima(ctx, "organico.csv")) and num.numero(o.get("seguidores")):
        salida["Seguidores y crecimiento"] = (
            f"{_numero(num.numero(o.get('seguidores')))} ({_t(o.get('mes'))})"
        )
    if (c := _ultima(ctx, "clientas.csv")) is not None:
        nuevas = num.numero(c.get("clientas_nuevas")) or 0
        recompras = num.numero(c.get("recompras"))
        if recompras is not None and nuevas + recompras:
            salida["Recompra"] = (
                f"{recompras / (nuevas + recompras) * 100:.0f} % ({_t(c.get('mes'))})"
            )
        if num.numero(c.get("nps_promedio")) is not None:
            salida["Satisfacción (NPS) y reseñas"] = (
                f"{num.numero(c.get('nps_promedio')):.1f} de 10".replace(".", ",")
            )
        if num.numero(c.get("fotos_recibidas")) is not None:
            salida["Fotos y videos de clientas conseguidos"] = (
                f"{_numero(num.numero(c.get('fotos_recibidas')))} ({_t(c.get('mes'))})"
            )
    contenido = num.leer_csv(ctx.carpeta.tabla("datos/contenido.csv"))
    if contenido:
        ultimos = [
            f
            for f in contenido
            if f.get("fecha", "") >= (ctx.hoy.replace(day=1)).isoformat()
        ]
        salida["Publicaciones por semana"] = f"{len(ultimos)} este mes"
    competencia = num.leer_csv(ctx.carpeta.tabla("datos/competencia.csv"))
    if competencia:
        marcas = {f.get("marca") for f in competencia if f.get("marca")}
        salida["Anuncios de la competencia"] = (
            f"{len(competencia)} vistos de {len(marcas)} marca(s)"
        )
    if ctx.bot is not None and not ctx.bot.de_prueba and ctx.bot.ventas:
        b = ctx.bot
        total = (b.principales[0] + b.resto[0]) or 1
        salida["Ventas por ciudad"] = (
            f"{b.resto[0] / total * 100:.0f} % fuera de Bogotá, Medellín y Cali"
        )
        if b.mezcla:
            salida["Mezcla 1 · 2 · 3 huellitas"] = " · ".join(
                f"{n}: {c}" for n, c in b.mezcla
            )
    elif ciudades := num.leer_csv(ctx.carpeta.tabla("datos/ciudades.csv")):
        salida["Ventas por ciudad"] = f"{len(ciudades)} fila(s) en datos/ciudades.csv"
    if ctx.foto_erp:
        costos = [
            num.numero(p.get("Costo_Total"))
            for p in ctx.foto_erp.get("productos", [])
            if "anillo" in str(p.get("Producto", "")).lower()
        ]
        costos = [x for x in costos if x]
        receta = f"receta del ERP {_pesos(min(costos))}" if costos else ""
        if real := num.numero(ctx.foto_erp.get("costo_real")):
            salida["Costo real por anillo"] = (
                f"{_pesos(real)} hoy (ERP: plata del mes, salario de Lía y gastos)"
                + (f" · {receta} solo materiales y mano de obra" if receta else "")
                + " · ver Finanzas → Costos"
            )
        elif receta:
            salida["Costo real por anillo"] = (
                f"{receta} (falta el costo real) · ver «El ERP»"
            )
    return salida


def _seccion_biblioteca(ctx: Contexto) -> str:
    grupos = (
        ("El estándar del panel", ["ESTANDAR-DEL-PANEL.md", "PEDIDOS-AL-PANEL.md"]),
        (
            "Estado y plan",
            [
                "ESTADO.md",
                "PLAN-CAMPANA.md",
                "CAMPANA-OCTUBRE.md",
                "PENDIENTES.md",
                "TRABAJO-AUTONOMO.md",
                "README.md",
            ],
        ),
        ("Lo aprendido", ["APRENDIZAJES.md", "experimentos/EXPERIMENTOS.md"]),
        (
            "Creativos",
            [r for r in sorted(ctx.carpeta.docs) if r.startswith("creativos/")],
        ),
        (
            "El negocio y las cuentas",
            ["negocio.md", "cuenta-instagram.md", "datos/meta_cuenta.md"],
        ),
        (
            "Bitácora (lo más nuevo primero)",
            sorted(
                (r for r in ctx.carpeta.docs if r.startswith("bitacora/")), reverse=True
            ),
        ),
    )
    usados = {r for _, rutas in grupos for r in rutas}
    otros = sorted(r for r in ctx.carpeta.docs if r not in usados)
    partes = []
    for titulo, rutas in (*grupos, ("Otros documentos", otros)):
        docs = [x for x in (_documento(ctx, r) for r in rutas) if x]
        if docs:
            partes.append(f"<h3>{titulo}</h3>{''.join(docs)}")
    tablas = [
        f"<details class=doc><summary>📊 {_t(ruta.rsplit('/', 1)[-1])}"
        f"<small>{_t(ruta)}</small></summary>{_tabla(texto)}</details>"
        for ruta, texto in sorted(ctx.carpeta.tablas.items())
    ]
    if tablas:
        partes.append(f"<h3>Las tablas de datos</h3>{''.join(tablas)}")
    if not partes:
        return ""
    return (
        "<section><h2 id=biblioteca>Toda la carpeta de marketing</h2>"
        f"<p class=ayuda>{len(ctx.carpeta.docs) + 1} documentos y "
        f"{len(ctx.carpeta.tablas)} tablas, tal cual los dejó el Claude de marketing. "
        f"Toca uno para abrirlo.</p>{''.join(partes)}</section>"
    )


# ---------------------------------------------------------------------------
# Fase 3 (01/10): el estándar, la semana, las plantillas, el bot y el ERP
# ---------------------------------------------------------------------------


def _ganancia_por_anillo(ctx: Contexto) -> float:
    """Lo que deja una pieza antes de pauta: precio promedio − costo de hoy, del ERP
    (02/10). Sin foto del ERP, lo de la carpeta de marketing."""
    f = ctx.foto_erp or {}
    real = _n(f.get("costo_real"))
    meses = [m for m in f.get("mensual", []) if _n(m.get("Unidades"))]
    if real and meses:
        piezas = sum(_n(m.get("Unidades")) for m in meses)
        return sum(_n(m.get("Ingresos")) for m in meses) / piezas - real
    r = ctx.d.get("rentabilidad") if isinstance(ctx.d.get("rentabilidad"), dict) else {}
    return _n(r.get("ganancia_por_anillo_cop")) or num.GANANCIA_POR_ANILLO


def _semaforo(costo: float) -> tuple[str, str]:
    """(tono, qué hacer) según las «Reglas de cada lunes» de marketing."""
    if costo <= num.META_COSTO_POR_VENTA:
        return "bueno", "En la meta. Si se repite dos semanas: subir el presupuesto 20 %."
    if costo <= num.AVISO_COSTO_POR_VENTA:
        return "bueno", "Va bien. No tocar nada."
    if costo <= num.MALO_COSTO_POR_VENTA:
        return "neutro", "No tocar, pero avisar a Camilo."
    return (
        "malo",
        "Si se repite dos semanas: bajar el presupuesto 30 % y avisar a Camilo.",
    )


def _seccion_semana(ctx: Contexto) -> str:
    """El medidor del lunes: la última fila de `datos/semanal.csv`."""
    filas = [
        f
        for f in num.leer_csv(ctx.carpeta.tabla("datos/semanal.csv"))
        if num.numero(f.get("gasto_cop")) is not None
    ]
    if not filas:
        return (
            "<section><h2 id=semana>La cuenta de esta semana</h2><article>"
            "<p class=ayuda>⏳ Aún sin semanas. Cada lunes, una fila en "
            "<code>datos/semanal.csv</code> (el lunes de la semana, lo gastado y los "
            "anillos vendidos) y aquí sale sola la cuenta: costo por venta, ganancia y "
            "el color del semáforo, con lo que toca hacer.</p></article></section>"
        )
    f = sorted(filas, key=lambda x: x.get("semana", ""))[-1]
    gasto = num.numero(f.get("gasto_cop")) or 0
    anillos = num.numero(f.get("anillos")) or 0
    ganancia = anillos * _ganancia_por_anillo(ctx) - gasto
    if anillos:
        costo = gasto / anillos
        tono, hacer = _semaforo(costo)
        cuenta = f"cada venta costó <b>{_pesos(costo)}</b>"
    else:
        tono, hacer = "malo", "Una semana sin ventas: bajar 30 % y avisar a Camilo."
        cuenta = "<b>sin ventas</b>"
    return (
        f"<section><h2 id=semana>La cuenta de la semana del {_fecha(f.get('semana'))}"
        f"</h2><div class='regla {tono}'><div class=si>Se gastaron {_pesos(gasto)} y se "
        f"vendieron {_numero(anillos)} anillos: {cuenta}; quedaron <b>{_pesos(ganancia)}"
        f"</b> de ganancia.</div><div class=hacer>→ {_t(hacer)}</div></div>"
        + _calculado("datos/semanal.csv y las reglas de cada lunes")
        + "</section>"
    )


def _seccion_semanas(ctx: Contexto) -> str:
    filas = sorted(
        num.leer_csv(ctx.carpeta.tabla("datos/semanal.csv")),
        key=lambda x: x.get("semana", ""),
    )
    if not filas:
        return ""
    gpa = _ganancia_por_anillo(ctx)
    puntos, cuerpo = [], []
    for f in filas:
        gasto = num.numero(f.get("gasto_cop")) or 0
        anillos = num.numero(f.get("anillos")) or 0
        costo = gasto / anillos if anillos else None
        if costo is not None:
            puntos.append((_fecha(f.get("semana")), round(costo)))
        tono = _semaforo(costo)[0] if costo is not None else "malo"
        color = {"bueno": "g-moderada", "malo": "g-alta"}.get(tono, "")
        cuerpo.append(
            f"<tr class='{color}'>"
            f"<td>{_fecha(f.get('semana'))}</td><td class=n>{_pesos(gasto)}</td>"
            f"<td class=n>{_numero(anillos)}</td>"
            f"<td class=n>{_pesos(costo) if costo is not None else '—'}</td>"
            f"<td class=n>{_pesos(anillos * gpa - gasto)}</td>"
            f"<td>{_t(f.get('decision') or '')}</td></tr>"
        )
    return (
        "<section><h2 id=semanas>Semana a semana</h2><article><div class=desliza>"
        "<table class='tabla datos rentabilidad'><tr><th>Semana</th><th>Gasto</th>"
        "<th>Anillos</th><th>Cada venta</th><th>Ganancia</th><th>Decisión</th></tr>"
        f"{''.join(cuerpo)}</table></div></article>"
        + _grafica_de(
            "Costo por venta, semana a semana", puntos, "cop", "datos/semanal.csv"
        )
        + "</section>"
    )


def _seccion_presupuesto(ctx: Contexto) -> str:
    filas = num.leer_csv(ctx.carpeta.tabla("datos/presupuesto.csv"))
    if not filas:
        return _plantilla_vacia(
            "presupuesto.csv",
            "El presupuesto del mes",
            "presupuesto",
            "Con el tope de cada mes aquí se ve cuánto se lleva gastado y si va al "
            "ritmo.",
        )
    gastos = {m.mes: m.pauta for m in ctx.meses}
    partes = []
    for f in sorted(filas, key=lambda x: x.get("mes", ""), reverse=True)[:6]:
        tope = num.numero(f.get("tope_cop")) or 0
        gastado = gastos.get(f.get("mes", "")) or 0
        uso = gastado / tope * 100 if tope else 0
        partes.append(
            f"<div class=barra><span>{_t(_corto(f.get('mes', '')))}</span><span "
            "class=fondo>"
            f"<span class=lleno style='display:block;width:{min(uso, 100):.0f}%;"
            f"background:{'#c96f5b' if uso > 100 else '#6f9e7f'}'></span></span>"
            f"<span class=cuanto>{uso:.0f} %</span></div>"
        )
    return (
        "<section><h2 id=presupuesto>El presupuesto del mes</h2><article>"
        "<p class=ayuda>Cuánto del tope de cada mes ya se gastó (rojo = se pasó).</p>"
        f"<div class=barras>{''.join(partes)}</div>"
        + _calculado("datos/presupuesto.csv y datos/meta_mensual.csv")
        + "</article></section>"
    )


def _plantilla_vacia(archivo: str, titulo: str, ancla: str, para_que: str) -> str:
    esquema = estandar.POR_ARCHIVO.get(archivo)
    columnas = ", ".join(c.nombre for c in esquema.columnas) if esquema else ""
    return (
        f"<section><h2 id={ancla}>{_t(titulo)}</h2><article><p class=ayuda>⏳ Aún sin "
        f"datos. {_t(para_que)} Se llena en <code>datos/{_t(archivo)}</code> "
        f"(columnas: {_t(columnas)}).</p></article></section>"
    )


def _seccion_tabla_del_estandar(
    ctx: Contexto, archivo: str, titulo: str, ancla: str, para_que: str
) -> str:
    """Una tabla del estándar: con filas, la tabla; sin filas, cómo se llena."""
    filas = num.leer_csv(ctx.carpeta.tabla(f"datos/{archivo}"))
    if not filas:
        return _plantilla_vacia(archivo, titulo, ancla, para_que)
    columnas = [c.nombre for c in estandar.POR_ARCHIVO[archivo].columnas]
    columnas = [c for c in columnas if any(c in f for f in filas)]
    orden = sorted(
        filas, key=lambda f: f.get("mes") or f.get("fecha") or "", reverse=True
    )
    return (
        f"<section><h2 id={ancla}>{_t(titulo)}</h2><p class=ayuda>{_t(para_que)}</p>"
        f"{_tabla('', columnas, orden)}</section>"
    )


def _seccion_pedidos(ctx: Contexto, compacto: bool = False) -> str:
    texto = ctx.carpeta.doc("PEDIDOS-AL-PANEL.md")
    pendientes = estandar.pedidos_pendientes(texto)
    if compacto:
        if not pendientes:
            return ""
        return (
            "<section><div class='alerta aviso'><b>📝 "
            f"{len(pendientes)} pedido(s) del marketing al panel</b>"
            f"{_t(' · '.join(pendientes))}. Camilo: pásaselos al Claude de VentaBot "
            "(están en Biblioteca).</div></section>"
        )
    if not texto:
        return ""
    return (
        "<section><h2 id=pedidos>Pedidos al panel "
        f"<span class=cuenta>{len(pendientes)}</span></h2><p class=ayuda>Lo que el "
        "marketing necesita que el panel tenga. Camilo se los pasa al Claude de "
        "VentaBot.</p>"
        + _documento(ctx, "PEDIDOS-AL-PANEL.md", abierto=bool(pendientes))
        + "</section>"
    )


def _seccion_calidad(ctx: Contexto) -> str:
    """Qué sirve y qué no: la revisión del estándar sobre la carpeta puesta."""
    i = ctx.informe
    if i is None:
        return ""
    lineas = []
    for archivo in i.tablas_conocidas:
        vacia = archivo in i.plantillas_vacias
        icono, que = ("⏳", "plantilla sin filas todavía") if vacia else ("✅", "se usa")
        lineas.append(
            f"<div class='ind {'no' if vacia else 'si'}'><span>{icono}</span>"
            f"<div><b>datos/{_t(archivo)}</b><small>{que}</small></div></div>"
        )
    for archivo in i.tablas_desconocidas:
        lineas.append(
            f"<div class='ind no'><span>❓</span><div><b>datos/{_t(archivo)}</b>"
            "<small>el panel no la conoce: solo en Biblioteca</small></div></div>"
        )
    faltan = [
        t
        for t in estandar.ESQUEMAS
        if t.archivo not in i.tablas_conocidas and t.archivo not in i.tablas_desconocidas
    ]
    for t in faltan:
        lineas.append(
            f"<div class='ind no'><span>➖</span><div><b>datos/{_t(t.archivo)}</b>"
            f"<small>no está en la carpeta ({_t(t.para_que)})</small></div></div>"
        )
    avisos = "".join(f"<li>{_t(a)}</li>" for a in i.avisos)
    version = i.version_del_estandar_en_la_carpeta
    return (
        "<section><h2 id=calidad>Calidad de los datos</h2><article>"
        f"<p class=ayuda>Revisión del estándar (versión {estandar.VERSION}) sobre lo que "
        f"está subido. La carpeta tiene la copia "
        f"{'v' + str(version) if version else '— (falta ESTANDAR-DEL-PANEL.md)'}. "
        f"{'✅ Sin errores.' if i.ok else '❌ Con errores.'} "
        f"{len(i.avisos)} aviso(s).</p>{''.join(lineas)}"
        + (
            f"<details class=doc><summary>⚠️ Los avisos<small>pasan, pero hay que "
            f"arreglarlos</small></summary><ul class=pasos>{avisos}</ul></details>"
            if avisos
            else ""
        )
        + "</article></section>"
    )


def _seccion_bot(ctx: Contexto) -> str:
    b = ctx.bot
    if b is None:
        return ""
    etiqueta = (
        "<div class='alerta aviso'><b>🧪 Datos de PRUEBA</b>El bot todavía no tiene "
        "ventas reales: esto sale de las charlas de ensayo. El día de «Pasar a real» "
        "(instructivo §10) se pone VENTAS_REALES_DESDE y desde ahí solo cuentan las de "
        "verdad.</div>"
        if b.de_prueba
        else ""
    )
    if not b.pedidos:
        return (
            f"<section><h2 id=bot>Lo que vende el bot</h2>{etiqueta}<article><p "
            "class=ayuda>Todavía no hay pedidos.</p></article></section>"
        )
    fichas = "".join(
        f"<div class=kpi><div class=etiqueta>{e}</div><div class=valor>{v}</div></div>"
        for e, v in (
            ("Pedidos (se pidió el abono)", _numero(b.pedidos)),
            ("Ventas (abono confirmado)", _numero(b.ventas)),
            ("Entregados", _numero(b.entregados)),
            ("Vendido", _pesos(b.ingresos)),
            (
                "Días hasta el abono",
                f"{b.dias_hasta_abono:.1f}".replace(".", ",")
                if b.dias_hasta_abono is not None
                else "—",
            ),
            ("Pedido → venta", f"{b.ventas / b.pedidos * 100:.0f} %"),
        )
    )
    ciudades = "".join(
        f"<tr><td>{_t(c)}</td><td class=n>{_numero(n)}</td><td "
        f"class=n>{_pesos(p)}</td></tr>"
        for c, n, p in b.por_ciudad
    )
    total = (b.principales[0] + b.resto[0]) or 1
    grupos = (
        f"<tr class=g-moderada><td>Bogotá · Medellín · Cali</td><td class=n>"
        f"{_numero(b.principales[0])}</td><td class=n>{_pesos(b.principales[1])}</td>"
        f"<td class=n>{b.principales[0] / total * 100:.0f} %</td></tr>"
        f"<tr class=g-alta><td>Resto de Colombia</td><td class=n>{_numero(b.resto[0])}"
        f"</td><td class=n>{_pesos(b.resto[1])}</td>"
        f"<td class=n>{b.resto[0] / total * 100:.0f} %</td></tr>"
    )
    mezcla = " · ".join(
        f"{n} huellita{'s' if n > 1 else ''}: <b>{c}</b>" for n, c in b.mezcla
    )
    return (
        f"<section><h2 id=bot>Lo que vende el bot</h2>{etiqueta}"
        f"<div class=kpis>{fichas}</div>"
        "<article><b>Las tres ciudades contra el resto (la prueba «Resto de Colombia»)"
        "</b><div class=desliza><table class='tabla datos "
        "rentabilidad'><tr><th>Grupo</th>"
        f"<th>Anillos</th><th>Vendido</th><th>%</th></tr>{grupos}</table></div>"
        + (f"<p class=dato-par><b>Qué anillos:</b> {mezcla}</p>" if mezcla else "")
        + "</article><details class=doc><summary>🏙️ Cada ciudad<small>de los pedidos del "
        "bot</small></summary><div class=desliza><table class='tabla "
        "datos'><tr><th>Ciudad"
        f"</th><th>Anillos</th><th>Vendido</th></tr>{ciudades}</table></div></details>"
        + _calculado("los pedidos del bot (tabla de análisis)")
        + "</section>"
    )


def _costo_del_anillo(ctx: Contexto, f: dict) -> list[str]:
    """El costo de una pieza HOY (Config del ERP = hoja Costeo, 02/10).

    El ERP manda: lo calcula con la plata del mes, los gramos reales, el salario
    de Lía y los demás gastos. Si la carpeta de marketing todavía trae otro
    costo, es un aviso (el panel ya usa el del ERP), no una decisión pendiente.
    """
    r = ctx.d.get("rentabilidad") if isinstance(ctx.d.get("rentabilidad"), dict) else {}
    costo_mkt = num.numero(r.get("costo_por_anillo_cop"))
    real = num.numero(f.get("costo_real"))
    enlace = (
        f"<a href='/panel/finanzas?token={ctx.token}&vista=costos'>Finanzas → Costos</a>"
    )
    if not real:
        return [
            "<div class='alerta aviso'><b>🧾 Falta el costo del ERP</b>Se calcula con "
            "<code>vb erp --montar</code> (hoja Costeo). Mientras, el marketing usa el "
            "de su carpeta.</div>"
        ]
    salida = [
        "<div class='alerta bien'><b>🧾 Una pieza cuesta hoy "
        f"{_pesos(real)} (ERP)</b>Con la plata de este mes, los gramos reales, el "
        "salario de Lía, taller, familia, diligencias, equipos y colchón. Deja "
        f"{_pesos(_ganancia_por_anillo(ctx))} antes de pauta: una venta que cueste más "
        f"en publicidad pierde plata. Capa por capa en {enlace}.</div>"
    ]
    if costo_mkt and abs(costo_mkt - real) / real > 0.02:
        salida.append(
            "<div class='alerta aviso'><b>📁 La carpeta de marketing trae otro costo</b>"
            f"Dice {_pesos(costo_mkt)}; el panel ya usa el del ERP ({_pesos(real)}). En "
            "la próxima subida, el Claude de marketing debe tomar el costo del ERP "
            "(está en su estándar).</div>"
        )
    return salida


def _seccion_erp(ctx: Contexto) -> str:
    f = ctx.foto_erp
    boton = (
        f"<form method=post action='/panel/marketing/erp?token={ctx.token}'>"
        "<button class=principal>🔄 Actualizar del ERP</button></form>"
    )
    if not f:
        return (
            "<section><h2 id=erp>El ERP</h2><article><p class=ayuda>Todavía no hay foto "
            "del ERP: se toma al subir la carpeta de marketing o con este botón.</p>"
            f"{boton}</article></section>"
        )
    partes = []
    if ctx.ventas_de_prueba:
        partes.append(
            "<div class='alerta aviso'><b>🧪 Las ventas del ERP son de PRUEBA</b>La "
            "pauta (hoja Publicidad) sí es real: la llena el marketing. Las ventas se "
            "vuelven reales el día de «Pasar a real» (instructivo §10).</div>"
        )
    partes.extend(_costo_del_anillo(ctx, f))
    meses = f.get("mensual", [])[-6:]
    if meses:
        filas = "".join(
            f"<tr><td>{_t(m.get('MesKey'))}</td><td "
            f"class=n>{_pesos(num.numero(m.get('Ingresos')) or 0)}</td>"
            f"<td class=n>{_numero(num.numero(m.get('Unidades')) or 0)}</td>"
            f"<td class=n>{_pesos(num.numero(m.get('Publicidad')) or 0)}</td>"
            f"<td class=n>{_pesos(num.numero(m.get('Gastos')) or 0)}</td>"
            "<td "
            f"class=n><b>{_pesos(num.numero(m.get('Utilidad_Op')) or 0)}</b></td></tr>"
            for m in meses
        )
        partes.append(
            "<article><b>El estado de resultados (hoja Mensual)</b><div class=desliza>"
            "<table class='tabla "
            "datos'><tr><th>Mes</th><th>Ingresos</th><th>Unidades</th>"
            f"<th>Publicidad</th><th>Gastos</th><th>Utilidad</th></tr>{filas}</table>"
            "</div></article>"
        )
    if f.get("grupos"):
        filas = "".join(
            f"<tr><td>{_t(g.get('grupo'))}</td><td "
            f"class=n>{_numero(num.numero(g.get('unidades')) or 0)}</td>"
            f"<td class=n>{_pesos(num.numero(g.get('ingresos')) or 0)}</td></tr>"
            for g in f["grupos"]
        )
        partes.append(
            "<article><b>Ciudades en el ERP (hoja Rank_Ciudades)</b><div class=desliza>"
            "<table class='tabla datos'><tr><th>Grupo</th><th>Unidades</th><th>Ingresos"
            f"</th></tr>{filas}</table></div></article>"
        )
    if f.get("revisar"):
        partes.append(
            "<article><b>⚠️ Lo que el ERP marca para revisar</b><ul class=pasos>"
            + "".join(
                f"<li>{_t(v.get('chequeo'))}: {_t(v.get('resultado'))}</li>"
                for v in f["revisar"]
            )
            + "</ul></article>"
        )
    return (
        "<section><h2 id=erp>El ERP</h2><p class=ayuda>Foto del "
        f"{_t(str(f.get('leido', ''))[:16].replace('T', ' '))} (UTC). La pauta va sola a "
        "la hoja Publicidad cada vez que se sube el marketing.</p>"
        + "".join(partes)
        + boton
        + "</section>"
    )


# ---------------------------------------------------------------------------
# Las pestañas, en orden. Dentro de cada una se respeta el orden del formato
# (§3.3 de PARA-EL-PANEL.md). Una sección que no tiene datos no sale.
# ---------------------------------------------------------------------------


def _resumen(ctx: Contexto) -> str:
    meta = ctx.d.get("meta") if isinstance(ctx.d.get("meta"), dict) else {}
    if not meta.get("resumen"):
        return ""
    return f"<section><article><p>{_t(meta.get('resumen'))}</p></article></section>"


def _piloto(nombre: str) -> Callable[[Contexto], str]:
    """Una sección de la pestaña «Piloto» (vive en `marketing_piloto`, que importa
    de aquí: se carga al dibujarla, no al importar)."""

    def hacer(ctx: Contexto) -> str:
        from app.api.marketing_piloto import SECCIONES

        return dict(SECCIONES)[nombre](ctx)

    return hacer


VISTAS: tuple[tuple[str, str, tuple[tuple[str, Callable[[Contexto], str]], ...]], ...] = (
    (
        "hoy",
        "Hoy",
        (
            ("Alertas", lambda c: _seccion_alertas(c.d)),
            ("Pedidos al panel", lambda c: _seccion_pedidos(c, compacto=True)),
            ("Lo que muestran los números", lambda c: _seccion_recomendaciones(c, True)),
            ("Resumen", _resumen),
            ("Qué hacer", lambda c: _seccion_tareas(c.d)),
            ("Cada lunes", lambda c: _seccion_reglas_semanales(c.d)),
            ("La cuenta de la semana", _seccion_semana),
            ("Esta semana", lambda c: _seccion_fechas(c.d, c.hoy, solo_proximas=True)),
            ("Falta saber", lambda c: _seccion_datos_que_faltan(c.d)),
        ),
    ),
    (
        "piloto",
        "🚀 Piloto",
        tuple(
            (nombre, _piloto(nombre))
            for nombre in (
                "Filtros",
                "Hoy",
                "Calificación",
                "Embudo",
                "La tabla",
                "Anuncios",
                "Lo que hay que hacer",
                "El plan",
            )
        ),
    ),
    (
        "numeros",
        "Números",
        (
            ("Cómo vamos", lambda c: _seccion_cifras(c.d)),
            ("Indicadores del mes", _seccion_kpis),
            ("Embudo", _seccion_embudo),
            ("Ganancia", _rentabilidad),
            ("Semana a semana", _seccion_semanas),
            ("Presupuesto", _seccion_presupuesto),
            ("Lo que vende el bot", _seccion_bot),
            ("El ERP", _seccion_erp),
            ("Gráficas", lambda c: _seccion_indicadores(c.d)),
            ("Historia", _seccion_graficas_de_tablas),
            ("Costo por venta", lambda c: _seccion_costo_por_venta(c.d)),
            (
                "Orgánico",
                lambda c: _seccion_tabla_del_estandar(
                    c,
                    "organico.csv",
                    "El Instagram sin pauta",
                    "organico",
                    "Seguidores, alcance y visitas al perfil, mes a mes.",
                ),
            ),
            (
                "Clientas",
                lambda c: _seccion_tabla_del_estandar(
                    c,
                    "clientas.csv",
                    "Las clientas",
                    "clientas",
                    "Nuevas, recompras, satisfacción (NPS) y fotos recibidas, por mes.",
                ),
            ),
            (
                "Ciudades",
                lambda c: _seccion_tabla_del_estandar(
                    c,
                    "ciudades.csv",
                    "Ventas por ciudad (de marketing)",
                    "ciudades",
                    "Mientras el bot no tenga ventas reales, las anota el marketing.",
                ),
            ),
            ("Tablas", _seccion_tablas_completas),
        ),
    ),
    (
        "campanas",
        "Campañas",
        (
            ("Campañas", _seccion_campanas),
            ("Anuncios", _seccion_anuncios),
            (
                "La cuenta",
                lambda c: _documentos(
                    c, "La cuenta de anuncios", "cuenta", ["datos/meta_cuenta.md"]
                ),
            ),
        ),
    ),
    (
        "creativos",
        "Creativos",
        (
            ("Videos", lambda c: _seccion_reels(c.d)),
            ("Producciones", _seccion_producciones),
            (
                "Contenido",
                lambda c: _seccion_tabla_del_estandar(
                    c,
                    "contenido.csv",
                    "El contenido orgánico",
                    "contenido",
                    "Cada publicación y cómo le fue: de aquí sale el próximo anuncio.",
                ),
            ),
            (
                "Competencia",
                lambda c: _seccion_tabla_del_estandar(
                    c,
                    "competencia.csv",
                    "La competencia, anuncio por anuncio",
                    "competencia",
                    "Quién pauta, qué y a qué precio.",
                ),
            ),
            ("Fórmula", lambda c: _seccion_formula(c.d)),
            ("Ideas", lambda c: _seccion_angulos(c.d)),
            (
                "Para crear",
                lambda c: _documentos(
                    c,
                    "Para crear contenido",
                    "crear",
                    [
                        "creativos/GANCHOS.md",
                        "creativos/BANCO-DE-IDEAS.md",
                        "creativos/CARRUSEL-COMO-PEDIR.md",
                        "creativos/CALENDARIO-ORGANICO.md",
                        "creativos/COMPETENCIA.md",
                    ],
                ),
            ),
        ),
    ),
    (
        "estrategia",
        "Estrategia",
        (
            ("Recomendaciones", _seccion_recomendaciones),
            ("Diagnóstico", lambda c: _seccion_diagnostico(c.d)),
            ("Pruebas", lambda c: _seccion_pruebas(c.d)),
            ("Perfil", lambda c: _seccion_perfil(c.d)),
            ("Calendario", lambda c: _seccion_fechas(c.d, c.hoy)),
            ("Aprendido", lambda c: _seccion_aprendizajes(c.d)),
            (
                "Planes",
                lambda c: _documentos(
                    c,
                    "El plan completo",
                    "planes",
                    [
                        "PLAN-CAMPANA.md",
                        "CAMPANA-OCTUBRE.md",
                        "experimentos/EXPERIMENTOS.md",
                        "creativos/PROPUESTA-BONO-REGALO.md",
                        "cuenta-instagram.md",
                        "ESTADO.md",
                    ],
                ),
            ),
        ),
    ),
    ("indicadores", "Indicadores", (("Indicadores", _seccion_indicadores_pro),)),
    (
        "biblioteca",
        "Biblioteca",
        (
            ("Calidad de los datos", _seccion_calidad),
            ("Pedidos al panel", _seccion_pedidos),
            ("Biblioteca", _seccion_biblioteca),
        ),
    ),
)

# ---------------------------------------------------------------------------
# La página
# ---------------------------------------------------------------------------


def _hoy() -> date:
    """Hoy en Colombia (el servidor vive en UTC: a las 7 p. m. ya sería mañana)."""
    return datetime.now(_COLOMBIA).date()


def leer(ruta) -> tuple[Tablero | None, str]:
    """(tablero, aviso). Sin tablero, el aviso dice por qué."""
    try:
        texto = ruta.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None, "Todavía no se ha subido el marketing."
    except OSError as exc:
        log.warning("marketing: no se pudo leer %s (%s)", ruta, exc)
        return None, "No se pudo abrir el archivo del marketing."
    try:
        return leer_tablero(texto), ""
    except ValueError as exc:
        log.warning("marketing: el tablero no se lee (%s)", exc)
        return None, f"El archivo del marketing llegó con un error: {exc}."


def pagina(
    carpeta,
    token: str,
    cabecera,
    vista: str = "hoy",
    hoy: date | None = None,
    *,
    bot_filas: list[dict] | None = None,
    reales_desde: str = "",
    foto_erp: dict | None = None,
    anio: str = "",
    mes: str = "",
    embudo_bot: list[dict] | None = None,
    piloto: dict | None = None,
) -> str:
    """La página entera. `cabecera` es la del panel (mismo estilo y la llave).

    `embudo_bot` (03/10) es el embudo del chat día por día y `piloto` los
    filtros de esa pestaña (campana, fase, por, plan).

    `bot_filas` son los pedidos del bot (tabla de análisis), `reales_desde` la
    fecha desde la que son de verdad y `foto_erp` lo último leído del ERP.
    `anio` y `mes` (02/10): el período; las tablas, el ERP y lo del bot se
    filtran, y todo lo calculado sale de ese período.
    """
    hoy = hoy or _hoy()
    tok = html.escape(token)
    datos = leer_carpeta(Path(carpeta))
    claves = [v[0] for v in VISTAS]
    vista = vista if vista in claves else "hoy"
    a = int(anio) if str(anio).isdigit() and 2000 <= int(anio) <= 2100 else None
    m = int(mes) if a and str(mes).isdigit() and 1 <= int(mes) <= 12 else None
    filtro = (f"&anio={a}" if a else "") + (f"&mes={m}" if m else "")
    prefijo = _prefijo(a, m)
    pestanas = "".join(
        f"<a href='/panel/marketing?token={tok}&vista={clave}{filtro}'"
        f"{' class=activa' if clave == vista else ''}>{nombre}</a>"
        for clave, nombre, _ in VISTAS
    )
    from app.api.marketing_piloto import ESTILO_PILOTO, JS_PILOTO

    cuerpo = [
        cabecera("Marketing · Luna Joyas").replace(
            "</style>", ESTILO_MARKETING + ESTILO_PILOTO + "</style>"
        ),
        "<header><h1>📣 Marketing</h1><div class=sub>"
        f"<a href='/panel?token={tok}'>← taller</a> · "
        f"<a href='/panel/todo?token={tok}'>todo</a></div>",
    ]
    tablero = datos.tablero
    if tablero is None and not datos.docs and not datos.tablas:
        cuerpo += [
            "</header><main><section><article>",
            f"<p><b>{_t(datos.problema)}</b></p>",
            "<p class=ayuda>El marketing lo escribe el Claude de marketing en "
            "<code>Documents\\GitHub\\marketing-lia</code> y se sube con "
            "<b>SUBIR-MARKETING.cmd</b> (doble clic en el PC de Camilo).</p>",
            "</article></section></main></body></html>",
        ]
        return "".join(cuerpo)

    if tablero is not None:
        dias = (hoy - tablero.actualizado).days
        cuerpo.append(
            f"<div class=revision>Revisión {tablero.revision} · "
            f"{_fecha(tablero.actualizado.isoformat())}"
            + (f" · <b>hace {dias} días</b>" if dias >= DIAS_PARA_AVISAR else "")
            + "</div>"
        )
    cuerpo.append(f"<nav class=pestanas>{pestanas}</nav>")
    cuerpo.append(_selector(tok, vista, _meses_con_datos(datos), a, m))
    cuerpo.append("</header><main>")

    avisos = []
    if tablero is None:
        avisos.append(
            f"<div class='alerta aviso'><b>⚠️ {_t(datos.problema)}</b>"
            "Se muestran los documentos y las tablas.</div>"
        )
    else:
        if (hoy - tablero.actualizado).days >= DIAS_PARA_AVISAR:
            avisos.append(
                f"<div class='alerta aviso'><b>⚠️ Esta revisión tiene "
                f"{(hoy - tablero.actualizado).days} días</b>Puede que el plan ya haya "
                "cambiado: pregúntale a Camilo si hay una más nueva.</div>"
            )
        if tablero.formato_mas_nuevo:
            avisos.append(
                "<div class='alerta aviso'><b>⚠️ Llegó un formato más nuevo</b>Se "
                "muestra todo lo conocido; lo nuevo aparece cuando se actualice el "
                "panel.</div>"
            )
    cuerpo.append("".join(avisos))

    if prefijo and bot_filas is not None:
        bot_filas = [
            f for f in bot_filas if str(f.get("creado") or "").startswith(prefijo)
        ]
    ctx = _contexto(
        _carpeta_del_periodo(datos, prefijo),
        hoy,
        bot_filas,
        reales_desde,
        _foto_del_periodo(foto_erp, prefijo),
        token,
    )
    if embudo_bot is not None and prefijo:
        embudo_bot = [
            f for f in embudo_bot if str(f.get("fecha", "")).startswith(prefijo)
        ]
    ctx.embudo_bot = embudo_bot
    ctx.piloto = {
        **{k: str(v) for k, v in (piloto or {}).items() if v},
        **({"anio": str(a)} if a else {}),
        **({"mes": str(m)} if m else {}),
    }
    secciones = next(v[2] for v in VISTAS if v[0] == vista)
    for nombre, hacer in secciones:
        try:
            cuerpo.append(hacer(ctx))
        except Exception as exc:  # una sección rota no tumba la página
            log.warning("marketing: la sección %s no se pudo mostrar (%s)", nombre, exc)
            cuerpo.append(
                "<section><div class='alerta aviso'><b>⚠️ La parte "
                f"«{_t(nombre)}» no se pudo mostrar</b>Llegó con un formato "
                "inesperado; avísale a Camilo.</div></section>"
            )
    siguiente = claves[(claves.index(vista) + 1) % len(claves)]
    nombre_siguiente = next(n for c, n, _ in VISTAS if c == siguiente)
    cuerpo.append(
        f"<p class=siguiente><a href='/panel/marketing?token={tok}&vista={siguiente}"
        f"{filtro}'>"
        f"Siguiente: {nombre_siguiente} →</a></p>"
    )
    cuerpo.append(
        "</main>"
        + _JS_COPIAR
        + (JS_PILOTO if vista == "piloto" else "")
        + "</body></html>"
    )
    return "".join(cuerpo)
