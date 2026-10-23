"""La pestaña «Piloto» del panel de marketing (03/10).

Camilo: «súbeme al panel todo PILOTO VENTABOT … ordénala para hacerla
escalable con desplegables y demás cosas relevantes para filtrar, gestionar y
mirar lo que se desea en el momento que se desee».

Qué hay, de arriba abajo (cada parte devuelve "" si no tiene qué mostrar):

1. **Los filtros**: campaña, fase y «ver por» (día, semana o fase). Son
   desplegables que recargan la página; se suman al período (año y mes).
2. **Hoy**: la fase que corre, el día, el presupuesto, cuándo se pasa y lo que
   viene; debajo, los FRENOS del plan, siempre a la vista.
3. **La calificación** (§7 del plan): las cinco notas, el total y la
   decisión. 🧮 Calculada con `app/domain/marketing_piloto.py`.
4. **El embudo**: conversaciones → enganchadas → listas para pagar → ventas,
   con gasto, costo por venta y ganancia.
5. **Día a día / semana / fase**: la tabla, con su nota por fila.
6. **Los anuncios**: su nota y cuál apagar.
7. **Lo que hay que hacer**: las tareas del tablero que son del piloto.
8. **El plan entero**, sección por sección, plegado, con buscador, «Ir a…» y
   abrir o cerrar todo. Un desplegable cambia de plan: cualquier PILOTO-*,
   PLAN-* o CAMPANA-* de la carpeta aparece solo (escalable).

Lo que pasa en el chat lo cuenta el bot (`tablero.embudo_por_dia`); lo de Meta
lo anota el marketing en `datos/piloto_dias.csv` y `datos/piloto_anuncios.csv`.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import date

from app.api import markdown_seguro as md
from app.api.marketing import (
    Contexto,
    _calculado,
    _fecha,
    _ganancia_por_anillo,
    _numero,
    _pesos,
    _seccion_tareas,
    _t,
)
from app.domain import marketing_piloto as pil

#: El plan que se abre si nadie escoge otro.
PLAN_POR_DEFECTO = "PILOTO-VENTABOT.md"
#: Qué documentos de la carpeta son planes de campaña (escalable: uno nuevo
#: con este nombre aparece solo en el desplegable).
_ES_PLAN = re.compile(r"^(PILOTO|PLAN|CAMPANA)[-_].*\.md$", re.IGNORECASE)
POR = {"dia": "Día", "semana": "Semana", "fase": "Fase"}

ESTILO_PILOTO = """
.filtros{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:14px;
background:var(--tarjeta);border:1px solid var(--borde);border-radius:12px;
padding:8px 10px;margin:8px 0}
.filtros label{display:flex;gap:6px;align-items:center}
.filtros select,.plan-barra select,.plan-barra input{font:inherit;padding:5px 8px;
border-radius:8px;border:1px solid var(--borde);max-width:100%}
.hoy-piloto .fase-hoy{font-size:18px;font-weight:700;margin:2px 0 4px}
.lineas-fases{list-style:none;padding:0;margin:8px 0 0}
.lineas-fases li{display:grid;grid-template-columns:1.6em 1fr;gap:6px;padding:6px 0;
border-bottom:1px solid var(--borde);font-size:14px}
.lineas-fases li.actual{background:#fff6e0;border-radius:8px;padding:6px}
.lineas-fases li.pasada{opacity:.55}
.notas-piloto{display:grid;gap:6px;margin:8px 0}
.nota-p{display:grid;grid-template-columns:2.2em 1fr auto;gap:8px;align-items:center;
border-radius:10px;padding:8px 10px;background:#f7f3f1;border-left:4px solid #b9a6a0;
font-size:14px}
.nota-p.p2{background:#eef6f0;border-color:#3f7d5a}
.nota-p.p1{background:#fff6e0;border-color:#d39b1f}
.nota-p.p0{background:#fbecea;border-color:#c0392b}
.nota-p .bola{font-size:20px;text-align:center}
.nota-p .valor{font-weight:700;white-space:nowrap}
.nota-p small{display:block;color:var(--suave);font-size:12px}
.total-p{font-size:22px;font-weight:700}
.plan-barra{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0 10px}
.plan-barra input{flex:1 1 180px}
.plan-barra button{padding:5px 10px}
.plan-cuenta{font-size:12px;color:var(--suave)}
details.seccion-plan.oculta{display:none}
details.seccion-plan mark{background:#ffe58a;padding:0 1px;border-radius:2px}
.apagar{color:#9b2c1e;font-weight:700}
"""

#: Buscador, «Ir a…», abrir o cerrar todo y abrir la sección de un enlace
#: «#plan-9». Sin librerías; si el JavaScript no corre, todo sigue legible.
JS_PILOTO = """
<script>
(function(){
const caja=document.getElementById('plan-buscar');if(!caja)return;
const secs=[...document.querySelectorAll('details.seccion-plan')];
const cuenta=document.getElementById('plan-cuenta');
const norm=s=>s.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();
secs.forEach(s=>{s.dataset.texto=norm(s.textContent)});
function buscar(){const q=norm(caja.value.trim());let n=0;
 secs.forEach(s=>{const si=!q||s.dataset.texto.includes(q);
  s.classList.toggle('oculta',!si);if(si)n++;if(q&&si)s.open=true});
 cuenta.textContent=q?(n+' de '+secs.length+' secciones'):''}
caja.addEventListener('input',buscar);
document.getElementById('plan-abrir').onclick=()=>secs.forEach(s=>s.open=true);
document.getElementById('plan-cerrar').onclick=()=>secs.forEach(s=>s.open=false);
const ir=document.getElementById('plan-ir');
ir.onchange=()=>{const s=document.getElementById(ir.value);if(s){s.open=true;
 s.scrollIntoView({behavior:'smooth'})}ir.value=''};
function alHash(){const s=document.getElementById(location.hash.slice(1));
 if(s&&s.matches('details')){s.open=true;s.scrollIntoView()}}
window.addEventListener('hashchange',alHash);alHash();
})();
</script>
"""


# ---------------------------------------------------------------------------
# Lo común
# ---------------------------------------------------------------------------


def _fases(ctx: Contexto) -> list[pil.Fase]:
    return pil.leer_fases(ctx.carpeta.tabla("datos/piloto_fases.csv"))


def _campana(ctx: Contexto, fases: list[pil.Fase]) -> str:
    nombres = pil.campanas(fases)
    pedida = ctx.piloto.get("campana", "")
    return pedida if pedida in nombres else (nombres[0] if nombres else "")


def _por(ctx: Contexto) -> str:
    por = ctx.piloto.get("por", "")
    return por if por in POR else "dia"


def _fase_pedida(ctx: Contexto) -> int | None:
    valor = str(ctx.piloto.get("fase", ""))
    return int(valor) if valor.isdigit() else None


def _dias(ctx: Contexto, fases: list[pil.Fase], campana: str) -> list[pil.Dia]:
    dias = pil.dias_de(
        fases,
        campana,
        ctx.carpeta.tabla("datos/piloto_dias.csv"),
        ctx.embudo_bot,
        ctx.hoy,
    )
    fase = _fase_pedida(ctx)
    if fase is not None:
        dias = [d for d in dias if d.fase and d.fase.numero == fase]
    return dias


def _pct(valor: float | None) -> str:
    if valor is None:
        return "—"
    return f"{valor:.1f} %".replace(".", ",")


def _valor(nota: pil.Nota, valor: float | None) -> str:
    if valor is None:
        return "—"
    if valor == float("inf"):
        return "sin ventas"
    return _pesos(valor) if nota.formato == "pesos" else _pct(valor)


def _que_ver(ctx: Contexto, campana: str) -> str:
    """Lo que se está viendo, en palabras."""
    fase = _fase_pedida(ctx)
    return (
        f"<b>{_t(campana)}</b> · "
        + (f"fase {fase}" if fase is not None else "todas las fases")
        + f" · por {POR[_por(ctx)].lower()}"
    )


# ---------------------------------------------------------------------------
# 1 y 2 · Los filtros y hoy
# ---------------------------------------------------------------------------


def seccion_filtros(ctx: Contexto) -> str:
    fases = _fases(ctx)
    campana = _campana(ctx, fases)
    nombres = pil.campanas(fases)
    if not nombres:
        return (
            "<section><h2 id=piloto>🚀 Piloto</h2><article><p class=ayuda>⏳ Aún no "
            "hay campañas piloto. El marketing las pone en <code>datos/"
            "piloto_fases.csv</code> (una fila por fase: campaña, fase, nombre, "
            "desde, hasta, presupuesto diario y cuándo se pasa) y aquí aparecen "
            "solas, con su calificación.</p></article></section>"
        )
    fase = _fase_pedida(ctx)
    numeros = sorted({x.numero for x in fases if x.campana == campana})

    def opciones(pares, actual) -> str:
        return "".join(
            f"<option value='{html.escape(str(v), quote=True)}'"
            f"{' selected' if v == actual else ''}>{_t(n)}</option>"
            for v, n in pares
        )

    escondidos = "".join(
        f"<input type=hidden name={k} value='{html.escape(str(v), quote=True)}'>"
        for k, v in (
            ("token", ctx.token),
            ("vista", "piloto"),
            ("anio", ctx.piloto.get("anio", "")),
            ("mes", ctx.piloto.get("mes", "")),
            ("plan", ctx.piloto.get("plan", "")),
        )
        if v
    )
    return (
        "<section><h2 id=piloto>🚀 Piloto</h2>"
        "<form method=get action='/panel/marketing' class=filtros>"
        f"{escondidos}"
        "<label>Campaña <select name=campana onchange='this.form.submit()'>"
        f"{opciones([(c, c) for c in nombres], campana)}</select></label>"
        "<label>Fase <select name=fase onchange='this.form.submit()'>"
        + opciones(
            [("", "Todas"), *[(str(n), f"Fase {n}") for n in numeros]],
            str(fase) if fase is not None else "",
        )
        + "</select></label><label>Ver por <select name=por "
        "onchange='this.form.submit()'>"
        f"{opciones(list(POR.items()), _por(ctx))}</select></label>"
        "<noscript><button>Ver</button></noscript></form>"
        f"<p class=ayuda>Viendo: {_que_ver(ctx, campana)}. Lo del chat lo cuenta el "
        "bot solo; lo de Meta, el marketing (<code>datos/piloto_dias.csv</code>).</p>"
        "</section>"
    )


def _seccion_del_plan(texto: str, palabra: str) -> str:
    """El cuerpo de la primera sección `##` cuyo título tiene `palabra`."""
    for titulo, cuerpo in _secciones(texto)[1]:
        if palabra in _sin_tildes(titulo):
            return cuerpo
    return ""


def seccion_hoy(ctx: Contexto) -> str:
    fases = _fases(ctx)
    campana = _campana(ctx, fases)
    if not campana:
        return ""
    propias = [x for x in fases if x.campana == campana]
    h = pil.hoy_en(fases, campana, ctx.hoy)
    if h.fase:
        f = h.fase
        de = f" de {f.dias}" if f.dias else ""
        titulo = f"Hoy: fase {f.numero} · {_t(f.nombre)} — día {h.dia}{de}"
    elif h.terminada:
        titulo = "La campaña terminó"
    elif h.proxima and h.proxima is propias[0]:
        n = h.dias_para_la_proxima
        titulo = (
            f"Arranca el {_fecha(h.proxima.desde.isoformat())} "
            f"(en {n} día{'s' if n != 1 else ''})"
        )
    else:
        titulo = "Entre fases: cerrando la anterior"
    detalle = []
    if h.fase and h.fase.diario:
        detalle.append(f"<b>{_pesos(h.fase.diario)}</b> al día")
    if h.fase and h.fase.conjuntos:
        detalle.append(_t(h.fase.conjuntos))
    if h.proxima and h.fase:
        detalle.append(
            f"la fase {h.proxima.numero} arranca el {_fecha(h.proxima.desde.isoformat())}"
        )
    pasa = (
        f"<p class=dato-par><b>Se pasa a la siguiente si:</b> {_t(h.fase.pasa_si)}</p>"
        if h.fase and h.fase.pasa_si
        else ""
    )
    lineas = []
    for x in propias:
        clase = (
            "actual" if h.fase is x else "pasada" if x.hasta and x.hasta < ctx.hoy else ""
        )
        hasta = f" → {_fecha(x.hasta.isoformat())}" if x.hasta else " en adelante"
        lineas.append(
            f"<li class='{clase}'><b>{x.numero}</b><div><b>{_t(x.nombre)}</b> · "
            f"{_fecha(x.desde.isoformat())}{hasta}"
            + (f" · {_pesos(x.diario)}/día" if x.diario else "")
            + (f"<br><small>{_t(x.pasa_si)}</small>" if x.pasa_si else "")
            + "</div></li>"
        )
    documento = propias[0].documento or PLAN_POR_DEFECTO
    frenos = _seccion_del_plan(ctx.carpeta.doc(documento), "freno")
    caja_frenos = (
        "<div class='alerta urgente'><b>🛑 Frenos: apagar de inmediato si…</b>"
        f"<div class=md>{md.a_html(frenos)}</div></div>"
        if frenos
        else ""
    )
    return (
        "<section><article class=hoy-piloto>"
        f"<div class=fase-hoy>{titulo}</div>"
        + (f"<p class=dato-par>{' · '.join(detalle)}</p>" if detalle else "")
        + pasa
        + f"<details class=doc><summary>📅 Las fases de {_t(campana)}<small>"
        f"de datos/piloto_fases.csv</small></summary><ol class=lineas-fases>"
        f"{''.join(lineas)}</ol></details>"
        "</article>" + caja_frenos + "</section>"
    )


# ---------------------------------------------------------------------------
# 3 · La calificación
# ---------------------------------------------------------------------------


def _tarjeta(cal: pil.Calificacion) -> str:
    filas = []
    for n in cal.notas:
        bola = {2: "🟢", 1: "🟡", 0: "🔴"}.get(n.puntos, "⚪")
        clase = f"p{n.puntos}" if n.puntos is not None else ""
        provisional = " · umbral provisional" if n.nota.provisional else ""
        filas.append(
            f"<div class='nota-p {clase}'><div class=bola>{bola}</div>"
            f"<div><b>{n.nota.numero} · {_t(n.nota.nombre)}</b>"
            f"<small>{_t(n.nota.mide)} · {_t(n.nota.umbrales)}{provisional}</small>"
            f"</div><div class=valor>{_valor(n.nota, n.valor)}</div></div>"
        )
    return f"<div class=notas-piloto>{''.join(filas)}</div>"


def seccion_calificacion(ctx: Contexto) -> str:
    fases = _fases(ctx)
    campana = _campana(ctx, fases)
    if not campana:
        return ""
    dias = _dias(ctx, fases, campana)
    t = pil.total(dias)
    cal = pil.calificar(t, _ganancia_por_anillo(ctx))
    tono, lectura, hacer = cal.lectura
    baja = cal.mas_baja
    arreglo = (
        f"<p class=dato-par><b>La nota más baja:</b> {baja.nota.numero} · "
        f"{_t(baja.nota.nombre)} → <a href='#plan-9'>qué se toca (§9 del plan)</a></p>"
        if baja and cal.completa and cal.puntos < 8
        else ""
    )
    if not dias:
        return (
            "<section><h2 id=calificacion>La calificación</h2><article><p "
            "class=ayuda>⏳ Todavía no hay días que calificar. En cuanto la campaña "
            "arranque, el bot cuenta las conversaciones y aquí salen las cinco "
            "notas.</p>" + _tarjeta(cal) + "</article></section>"
        )
    return (
        f"<section><h2 id=calificacion>La calificación <span class=cuenta>"
        f"{cal.puntos}/{cal.posibles or 10}</span></h2>"
        f"<div class='regla {tono}'><div class=si><span class=total-p>{cal.puntos} "
        f"de 10</span> · {_t(lectura)}</div><div class=hacer>→ {_t(hacer)}</div></div>"
        + arreglo
        + _tarjeta(cal)
        + "<p class=ayuda>Del período y la fase escogidos. Las notas 2 y 3 tienen "
        "umbrales provisionales: se recalibran con las primeras 150 "
        "conversaciones. Con poco volumen (fase 1) una venta de más o de menos lo "
        "cambia todo: se decide con cautela.</p>"
        + _calculado(
            "las reglas del §7 del plan, el chat del bot y datos/piloto_dias.csv"
        )
        + "</section>"
    )


# ---------------------------------------------------------------------------
# 4 y 5 · El embudo y la tabla
# ---------------------------------------------------------------------------


def seccion_embudo(ctx: Contexto) -> str:
    fases = _fases(ctx)
    campana = _campana(ctx, fases)
    dias = _dias(ctx, fases, campana) if campana else []
    if not dias:
        return ""
    t = pil.total(dias)
    gpa = _ganancia_por_anillo(ctx)
    ganancia = t.ventas * gpa - t.gasto
    base = t.conversaciones or 1

    def escalon(nombre: str, n: float, que: str) -> str:
        ancho = max(8, min(100, n / base * 100)) if t.conversaciones else 8
        return (
            f"<div class=escalon><div class=barra-embudo style='width:{ancho:.0f}%'>"
            f"{_numero(n)}</div><div class=nombre>{nombre} · "
            f"<b>{_pct(n / t.conversaciones * 100) if t.conversaciones else '—'}</b>"
            f"</div><div class=paso>{que}</div></div>"
        )

    fichas = "".join(
        f"<div class=kpi><div class=etiqueta>{e}</div><div class=valor>{v}</div></div>"
        for e, v in (
            ("Gasto", _pesos(t.gasto)),
            ("Conversaciones (Meta)", _numero(t.conversaciones_meta) or "—"),
            (
                "Costo por conversación",
                _pesos(t.costo_por_conversacion)
                if t.costo_por_conversacion is not None
                else "—",
            ),
            (
                "Costo por venta",
                _pesos(t.costo_por_venta) if t.costo_por_venta is not None else "—",
            ),
            ("Vendido", _pesos(t.ventas_cop)),
            ("Ganancia después de pauta", _pesos(ganancia)),
            ("Retención a 3 s", _pct(t.retencion_pct)),
        )
    )
    return (
        "<section><h2 id=embudo-piloto>El embudo</h2><article>"
        + escalon("Conversaciones", t.conversaciones, "escribieron al bot")
        + escalon("Enganchadas", t.enganchadas, "escogieron huellitas, colores o grabado")
        + escalon("Listas para pagar", t.listas, "recibieron el resumen y las cuentas")
        + escalon("Ventas", t.ventas, "abono confirmado")
        + f"</article><div class=kpis>{fichas}</div>"
        + _calculado(
            f"el chat del bot y datos/piloto_dias.csv; ganancia = ventas × "
            f"{_pesos(gpa)} (lo que deja una pieza) − gasto"
        )
        + "</section>"
    )


def seccion_tabla(ctx: Contexto) -> str:
    fases = _fases(ctx)
    campana = _campana(ctx, fases)
    dias = _dias(ctx, fases, campana) if campana else []
    if not dias:
        return ""
    gpa = _ganancia_por_anillo(ctx)
    por = _por(ctx)
    filas = []
    inicio = min((x.desde for x in fases if x.campana == campana), default=None)
    grupos = pil.agrupar(dias, por, inicio)
    if por == "dia":
        grupos = list(reversed(grupos))  # lo más nuevo arriba
    for etiqueta, t in grupos:
        cal = pil.calificar(t, gpa)
        nota = f"{cal.puntos}/{cal.posibles}" if cal.posibles else "—"
        titulo = _fecha(etiqueta) if por == "dia" else _t(etiqueta)
        filas.append(
            f"<tr><td>{titulo}</td><td class=n>{_pesos(t.gasto)}</td>"
            f"<td class=n>{_numero(t.conversaciones)}</td>"
            f"<td class=n>{_numero(t.enganchadas)}</td>"
            f"<td class=n>{_numero(t.listas)}</td>"
            f"<td class=n>{_numero(t.ventas)}</td>"
            f"<td class=n>{_pesos(t.costo_por_venta) if t.costo_por_venta else '—'}</td>"
            f"<td class=n>{_pesos(t.ventas * gpa - t.gasto)}</td>"
            f"<td class=n>{nota}</td><td>{_t(' · '.join(t.notas))}</td></tr>"
        )
    return (
        f"<section><h2 id=tabla-piloto>{POR[por]} a {POR[por].lower()}</h2>"
        "<details class=doc open><summary>📊 La tabla<small>cambia «Ver por» arriba "
        "para agrupar por semana o por fase</small></summary><div class=desliza>"
        "<table class='tabla datos rentabilidad'><tr><th>"
        f"{POR[por]}</th><th>Gasto</th><th>Conversaciones</th><th>Enganchadas</th>"
        "<th>Listas</th><th>Ventas</th><th>Cada venta</th><th>Ganancia</th>"
        f"<th>Nota</th><th>Notas</th></tr>{''.join(filas)}</table></div></details>"
        + _calculado("el chat del bot y datos/piloto_dias.csv")
        + "</section>"
    )


# ---------------------------------------------------------------------------
# 6 · Los anuncios
# ---------------------------------------------------------------------------


def _fila_de_anuncio(a: pil.Anuncio) -> str:
    t = a.totales
    dias = _numero(a.dias_en_pauta) if a.dias_en_pauta is not None else "—"
    costo = _pesos(t.costo_por_conversacion) if t.costo_por_conversacion else "—"
    posibles = a.calificacion.posibles if a.calificacion else 0
    apagar = " <span class=apagar>· apagar</span>" if a.apagar else ""
    return (
        f"<tr><td>{_t(a.nombre)}{apagar}</td><td class=n>{_pesos(t.gasto)}</td>"
        f"<td class=n>{dias}</td><td class=n>{_pct(t.retencion_pct)}</td>"
        f"<td class=n>{_numero(t.conversaciones)}</td><td class=n>{costo}</td>"
        f"<td class=n>{a.puntos}/{posibles}</td><td>{_t(a.notas)}</td></tr>"
    )


def seccion_anuncios(ctx: Contexto) -> str:
    fases = _fases(ctx)
    campana = _campana(ctx, fases)
    if not campana:
        return ""
    anuncios = pil.anuncios_de(
        ctx.carpeta.tabla("datos/piloto_anuncios.csv"), campana, _ganancia_por_anillo(ctx)
    )
    if not anuncios:
        return (
            "<section><h2 id=anuncios-piloto>Los anuncios</h2><article><p "
            "class=ayuda>⏳ Cada semana del piloto, una fila por anuncio en <code>datos/"
            "piloto_anuncios.csv</code> (semana, anuncio, gasto, días en pauta, "
            "retención a 3 s y conversaciones) y aquí sale su nota y cuál apagar. "
            "Con la atribución por anuncio también entran enganchadas y ventas."
            "</p></article></section>"
        )
    semanas: dict[date, list[pil.Anuncio]] = {}
    for a in anuncios:
        semanas.setdefault(a.semana, []).append(a)
    bloques = []
    for i, (semana, lista) in enumerate(sorted(semanas.items(), reverse=True)):
        filas = "".join(
            _fila_de_anuncio(a)
            for a in sorted(lista, key=lambda x: (-x.puntos, x.nombre))
        )
        bloques.append(
            f"<details class=doc{' open' if i == 0 else ''}><summary>📣 Semana del "
            f"{_fecha(semana.isoformat())}<small>{len(lista)} anuncios</small></summary>"
            "<div class=desliza><table class='tabla datos'><tr><th>Anuncio</th>"
            "<th>Gasto</th><th>Días</th><th>Retención 3 s</th><th>Conversaciones</th>"
            "<th>Cada conversación</th><th>Nota</th><th>Notas</th></tr>"
            f"{filas}</table></div></details>"
        )
    return (
        "<section><h2 id=anuncios-piloto>Los anuncios</h2>"
        "<p class=ayuda>«Apagar»: el de menor nota con 7 días y más de $30.000 "
        "gastados, si queda otro igual o mejor (§7 del plan). Sin atribución por "
        "anuncio solo se pone la nota 1.</p>"
        + "".join(bloques)
        + _calculado("datos/piloto_anuncios.csv y las reglas del §7")
        + "</section>"
    )


# ---------------------------------------------------------------------------
# 7 · Lo que hay que hacer
# ---------------------------------------------------------------------------


def seccion_tareas(ctx: Contexto) -> str:
    """Las tareas del tablero que son del piloto (id o título con «piloto»)."""
    tareas = [
        x
        for x in ctx.d.get("tareas") or []
        if isinstance(x, dict)
        and "piloto" in _sin_tildes(f"{x.get('id', '')} {x.get('titulo', '')}")
    ]
    if not tareas:
        return ""
    return _seccion_tareas({"tareas": tareas}).replace(
        "<h2 id=tareas>Qué hacer", "<h2 id=tareas-piloto>Lo que hay que hacer", 1
    )


# ---------------------------------------------------------------------------
# 8 · El plan, sección por sección
# ---------------------------------------------------------------------------


def _sin_tildes(texto: str) -> str:
    return (
        unicodedata.normalize("NFD", texto or "")
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )


def _secciones(texto: str) -> tuple[str, list[tuple[str, str]]]:
    """(lo de antes del primer `##`, [(título, cuerpo)…]). Los `##` dentro de un
    bloque de código no cortan."""
    intro: list[str] = []
    secciones: list[tuple[str, list[str]]] = []
    en_codigo = False
    for linea in (texto or "").replace("\r\n", "\n").split("\n"):
        if linea.strip().startswith("```"):
            en_codigo = not en_codigo
        if not en_codigo and linea.startswith("## "):
            secciones.append((linea[3:].strip(), []))
        elif secciones:
            secciones[-1][1].append(linea)
        else:
            intro.append(linea)
    return "\n".join(intro), [(t, "\n".join(c).strip()) for t, c in secciones]


def _ancla(titulo: str, i: int) -> str:
    """«9. Si una nota sale baja» → «plan-9»; sin número, por su posición."""
    m = re.match(r"^\s*(\d+)[.)]", titulo)
    return f"plan-{m.group(1)}" if m else f"plan-s{i}"


def planes(ctx: Contexto) -> list[str]:
    return sorted(r for r in ctx.carpeta.docs if "/" not in r and _ES_PLAN.match(r)) or (
        [PLAN_POR_DEFECTO] if ctx.carpeta.doc(PLAN_POR_DEFECTO) else []
    )


def seccion_plan(ctx: Contexto) -> str:
    disponibles = planes(ctx)
    if not disponibles:
        return ""
    pedido = ctx.piloto.get("plan", "")
    ruta = (
        pedido
        if pedido in disponibles
        else (PLAN_POR_DEFECTO if PLAN_POR_DEFECTO in disponibles else disponibles[0])
    )
    texto = ctx.carpeta.doc(ruta)
    intro, secciones = _secciones(texto)
    titulo = next((x[2:].strip() for x in intro.splitlines() if x.startswith("# ")), ruta)
    intro_sin_titulo = "\n".join(x for x in intro.splitlines() if not x.startswith("# "))
    opciones_plan = "".join(
        f"<option value='{html.escape(r, quote=True)}'{' selected' if r == ruta else ''}>"
        f"{_t(r.removesuffix('.md').replace('-', ' ').capitalize())}</option>"
        for r in disponibles
    )
    escondidos = "".join(
        f"<input type=hidden name={k} value='{html.escape(str(v), quote=True)}'>"
        for k, v in (
            ("token", ctx.token),
            ("vista", "piloto"),
            *(
                (k, ctx.piloto.get(k, ""))
                for k in ("campana", "fase", "por", "anio", "mes")
            ),
        )
        if v
    )
    ir = "<option value=''>Ir a…</option>" + "".join(
        f"<option value='{_ancla(t, i)}'>{_t(t)}</option>"
        for i, (t, _) in enumerate(secciones)
    )
    partes = []
    for i, (t, cuerpo) in enumerate(secciones):
        abierta = " open" if i == 0 else ""
        partes.append(
            f"<details class='doc seccion-plan' id='{_ancla(t, i)}'{abierta}>"
            f"<summary>{_t(t)}</summary><div class=md>{md.a_html(cuerpo)}</div>"
            "</details>"
        )
    return (
        "<section><h2 id=plan>📖 El plan</h2>"
        "<form method=get action='/panel/marketing' class=filtros>"
        f"{escondidos}<label>Plan <select name=plan onchange='this.form.submit()'>"
        f"{opciones_plan}</select></label><noscript><button>Ver</button></noscript>"
        "</form>"
        f"<article><b>{_t(titulo)}</b><div class=md>{md.a_html(intro_sin_titulo)}"
        "</div></article>"
        "<div class=plan-barra><input id=plan-buscar type=search "
        "placeholder='Buscar en el plan (ej.: presupuesto, anuncio C)'>"
        f"<select id=plan-ir>{ir}</select>"
        "<button type=button id=plan-abrir>Abrir todo</button>"
        "<button type=button id=plan-cerrar>Cerrar todo</button>"
        "<span id=plan-cuenta class=plan-cuenta></span></div>"
        + "".join(partes)
        + f"<p class=fuente>📄 {_t(ruta)}, tal cual lo escribió el marketing.</p>"
        "</section>"
    )


#: La pestaña, en orden (lo mismo que `VISTAS` de `marketing.py`).
SECCIONES = (
    ("Filtros", seccion_filtros),
    ("Hoy", seccion_hoy),
    ("Calificación", seccion_calificacion),
    ("Embudo", seccion_embudo),
    ("La tabla", seccion_tabla),
    ("Anuncios", seccion_anuncios),
    ("Lo que hay que hacer", seccion_tareas),
    ("El plan", seccion_plan),
)
