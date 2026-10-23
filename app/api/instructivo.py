"""El instructivo en el panel: `/panel/instructivo` (05/10).

Camilo, 05/10: «súbeme el instructivo como una sección del panel para que quede
ahí bien puesto, organizado y documentado todo».

Tres pestañas, cada una armada con su archivo del proyecto (el mismo que está
en GitHub): si se cambia el documento, la página cambia sola con el próximo
despliegue. No hay una copia que se pueda desactualizar.

- **Camilo**: `INSTRUCTIVO-PARA-CAMILO.md` — lo que te toca y cómo funciona todo.
- **Lía**: `MANUAL-DE-ATENCION.md` — cómo se atiende con el bot y Chatwoot.
- **Cómo está hecho**: `docs/sistema/*.md` — el sistema por dentro.

Cada sección (`##`) es un desplegable, con índice arriba, buscador (sin
recargar) y «abrir todo / cerrar todo». El Markdown pasa por
`markdown_seguro`: todo se escapa; lo único que se rearma son los
desplegables del manual de Lía (`<details>`/`<summary>`). Antes de mostrarlo se
enmascaran los correos y el tema secreto de los avisos (`_reservado`).
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.api import markdown_seguro as md

RAIZ = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Documento:
    clave: str
    pestana: str
    para_que: str
    archivos: tuple[str, ...]


DOCUMENTOS = (
    Documento(
        "camilo",
        "📘 Camilo",
        "Lo que te toca y cómo funciona todo: el día a día, Chatwoot, los avisos, el "
        "servidor, Meta, el ERP, la prueba de verdad y los recordatorios.",
        ("INSTRUCTIVO-PARA-CAMILO.md",),
    ),
    Documento(
        "lia",
        "💁 Lía",
        "Cómo se atiende con el bot y Chatwoot: qué hace solo el bot, qué te toca a "
        "ti, las etiquetas, los botones, qué hacer en cada caso y la chuleta.",
        ("MANUAL-DE-ATENCION.md",),
    ),
    Documento(
        "sistema",
        "🛠 Cómo está hecho",
        "El sistema por dentro, un documento por tema: el flujo de venta, la "
        "arquitectura, las reglas del negocio, los estados del pedido, Chatwoot, los "
        "datos, la observabilidad, el ERP y el glosario.",
        (),  # todos los de docs/sistema, en orden
    ),
)


def _archivos(doc: Documento) -> list[Path]:
    if doc.archivos:
        return [RAIZ / a for a in doc.archivos]
    return sorted(
        p for p in (RAIZ / "docs" / "sistema").glob("*.md") if p.name != "README.md"
    )


# ---------------------------------------------------------------------------
# Lo que no se muestra
# ---------------------------------------------------------------------------

_CORREO = re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
#: El tema de ntfy funciona como una contraseña: quien lo sepa lee los avisos.
_TEMA_DE_AVISOS = re.compile(r"\bventabot-[a-z0-9]{10,}\b")


def _reservado(texto: str) -> str:
    """Correos -> «p…@gmail.com»; el tema de los avisos -> «(en el .env)»."""
    texto = _CORREO.sub(lambda m: f"{m.group(1)}…@{m.group(2)}", texto)
    return _TEMA_DE_AVISOS.sub("ventabot-… (el tema está en el .env)", texto)


# ---------------------------------------------------------------------------
# De Markdown a secciones
# ---------------------------------------------------------------------------


@dataclass
class Seccion:
    titulo: str
    cuerpo: str  # Markdown
    ancla: str = ""


def _plano(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").lower()
    return "".join(c for c in t if not unicodedata.combining(c))


def ancla_de(titulo: str, usadas: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", _plano(re.sub(r"[*`]", "", titulo))).strip("-")
    base = (base or "seccion")[:60]
    ancla, n = base, 2
    while ancla in usadas:
        ancla, n = f"{base}-{n}", n + 1
    usadas.add(ancla)
    return ancla


def partir(texto: str) -> tuple[str, str, list[Seccion]]:
    """(título del documento, introducción, secciones `##`).

    Los `##` dentro de un bloque de código no parten nada. La sección
    «Índice» del documento se salta: la página arma el suyo.
    """
    titulo, intro, secciones = "", [], []
    actual: Seccion | None = None
    en_codigo = False
    for linea in texto.replace("\r\n", "\n").split("\n"):
        if linea.strip().startswith("```"):
            en_codigo = not en_codigo
        if not en_codigo and linea.startswith("# ") and not titulo:
            titulo = linea[2:].strip()
            continue
        if not en_codigo and linea.startswith("## "):
            actual = Seccion(linea[3:].strip(), "")
            secciones.append(actual)
            continue
        if actual is None:
            intro.append(linea)
        else:
            actual.cuerpo += linea + "\n"
    secciones = [s for s in secciones if _plano(s.titulo) != "indice"]
    return titulo, "\n".join(intro).strip(), secciones


_ENLACE_INTERNO = re.compile(r"\[([^\]]+)\]\((?!https?://)([^)\s]+)\)")
_DESPLEGABLE = re.compile(
    r"(<details(?:\s+open)?>|</details>|<summary>.*?</summary>)", re.I | re.S
)


def _preparar(texto: str) -> str:
    """Lo que el lector de Markdown no hace: enlaces al repo y `<br>`."""
    texto = _reservado(texto)

    def interno(m: re.Match) -> str:
        destino = m.group(2)
        if destino.startswith("#"):
            return m.group(1)  # un salto dentro del mismo documento
        return f"{m.group(1)} (`{destino}`)"

    texto = _ENLACE_INTERNO.sub(interno, texto)
    return re.sub(r"<br\s*/?>", "\n", texto, flags=re.I)


def a_html(texto: str) -> str:
    """Markdown -> HTML seguro, con los `<details>` del manual como desplegables.

    Todo lo demás que parezca HTML sale como texto (lo escapa `markdown_seguro`).
    """
    salida: list[str] = []
    abiertos = 0
    for trozo in _DESPLEGABLE.split(_preparar(texto)):
        bajo = trozo.lower()
        if bajo.startswith("<details"):
            salida.append(
                "<details class=sub open>" if "open" in bajo else "<details class=sub>"
            )
            abiertos += 1
        elif bajo == "</details>":
            if abiertos:
                salida.append("</details>")
                abiertos -= 1
        elif bajo.startswith("<summary>"):
            sin_etiquetas = re.sub(r"<[^>]+>", "", trozo[9:-10])
            salida.append(f"<summary>{md.en_linea(sin_etiquetas.strip())}</summary>")
        elif trozo.strip():
            salida.append(md.a_html(trozo))
    salida.extend("</details>" for _ in range(abiertos))
    return "\n".join(salida)


def secciones_de(doc: Documento) -> tuple[str, str, list[Seccion]]:
    """Las secciones de una pestaña. «Cómo está hecho»: un archivo = una sección."""
    usadas: set[str] = set()
    if doc.archivos:
        texto = _archivos(doc)[0].read_text(encoding="utf-8")
        titulo, intro, secciones = partir(texto)
    else:
        titulo, intro, secciones = doc.pestana, "", []
        for archivo in _archivos(doc):
            t, i, partes = partir(archivo.read_text(encoding="utf-8"))
            cuerpo = i + "\n\n" + "".join(f"## {p.titulo}\n{p.cuerpo}" for p in partes)
            secciones.append(Seccion(t or archivo.stem, cuerpo))
    for s in secciones:
        s.ancla = ancla_de(s.titulo, usadas)
    return titulo, intro, secciones


# ---------------------------------------------------------------------------
# La página
# ---------------------------------------------------------------------------

ESTILO_INSTRUCTIVO = """
.pestanas{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 10px}
.pestanas a{text-decoration:none;color:var(--texto);background:var(--tarjeta);
border:1px solid var(--borde);border-radius:999px;padding:6px 14px;font-weight:600}
.pestanas a.activa{background:var(--acento);border-color:var(--acento);color:#fff}
.herramientas{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
.herramientas input{flex:1;min-width:180px;font-size:16px;padding:8px 11px;
border:1px solid var(--borde);border-radius:10px;background:var(--tarjeta)}
.herramientas button{font-size:13px;padding:7px 11px;border:1px solid var(--borde);
border-radius:10px;background:var(--tarjeta);cursor:pointer}
.cuenta{font-size:13px;color:var(--suave)}
.indice{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 14px}
.indice a{font-size:13px;text-decoration:none;color:var(--texto);
background:var(--tarjeta);border:1px solid var(--borde);border-radius:999px;
padding:3px 10px}
.indice a:hover{border-color:var(--acento)}
details.sec{background:var(--tarjeta);border:1px solid var(--borde);border-radius:12px;
padding:10px 14px;margin-bottom:8px;scroll-margin-top:12px}
details.sec[open]{border-color:var(--acento)}
details.sec>summary{cursor:pointer;font-weight:700;font-size:16px}
details.sub{border-left:3px solid var(--borde);padding:2px 0 2px 10px;margin:8px 0}
details.sub>summary{cursor:pointer;font-weight:600}
.md{font-size:15px;line-height:1.6;overflow-wrap:anywhere}
.md h2,.md h3,.md h4,.md h5,.md h6{font-size:16px;margin:16px 0 6px}
.md ul,.md ol{padding-left:22px;margin:6px 0}
.md li{margin:3px 0}
.md blockquote{margin:8px 0;padding:6px 10px;border-left:3px solid var(--acento);
background:#faf3f5}
.md pre{white-space:pre-wrap;background:#f4f1f0;border-radius:8px;padding:8px;
font-size:12px}
.md code{background:#f4f1f0;border-radius:4px;padding:0 4px;font-size:13px}
.md hr{border:0;border-top:1px solid var(--borde);margin:12px 0}
.desliza{overflow-x:auto;margin:8px 0}
table.md{border-collapse:collapse;font-size:14px;min-width:100%}
table.md th,table.md td{border-bottom:1px solid var(--borde);padding:6px 7px;
text-align:left;vertical-align:top;overflow-wrap:normal;word-break:normal;min-width:6em}
.oculta{display:none}
.de-donde{font-size:12px;color:var(--suave);margin-top:18px}
"""

#: Lo único de JavaScript: el buscador, abrir/cerrar todo y abrir la sección del
#: índice. Sin él la página funciona igual (los desplegables son HTML).
_JS = """
<script>
const secs=[...document.querySelectorAll('details.sec')],q=document.getElementById('q'),
cuenta=document.getElementById('cuenta');
const plano=t=>t.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();
const textos=secs.map(s=>plano(s.textContent));
function buscar(){const v=plano(q.value.trim());let n=0;
 secs.forEach((s,i)=>{const si=!v||textos[i].includes(v);s.classList.toggle('oculta',!si);
  if(v)s.open=si;if(si)n++});
 cuenta.textContent=v?(n?n+' sección(es) con «'+q.value.trim()+'»':'Nada con eso'):''}
q.addEventListener('input',buscar);
document.getElementById('abrir').onclick=()=>secs.forEach(s=>s.open=true);
document.getElementById('cerrar').onclick=()=>secs.forEach(s=>s.open=false);
function alAncla(){const s=location.hash&&document.getElementById(location.hash.slice(1));
 if(s&&s.tagName==='DETAILS'){s.open=true;s.scrollIntoView()}}
addEventListener('hashchange',alAncla);alAncla();
</script>
"""


def pagina(token: str, cual: str, cabecera) -> str:
    """La página entera. `cabecera` es la del panel (mismo estilo y la llave)."""
    tok = html.escape(token)
    doc = next((d for d in DOCUMENTOS if d.clave == cual), DOCUMENTOS[0])
    titulo, intro, secciones = secciones_de(doc)
    cuerpo = [
        cabecera("Instructivo · Luna Joyas").replace(
            "</style>", ESTILO_INSTRUCTIVO + "</style>"
        ),
        "<header><h1>📖 Instructivo</h1><div class=sub>"
        f"<a href='/panel?token={tok}'>← taller</a> · "
        f"<a href='/panel/flujo?token={tok}'>el flujo (cada mensaje del bot)</a> · "
        f"<a href='/panel/chats?token={tok}'>conversaciones</a></div></header><main>",
        "<nav class=pestanas>",
    ]
    for d in DOCUMENTOS:
        activa = " class=activa" if d.clave == doc.clave else ""
        cuerpo.append(
            f"<a{activa} href='/panel/instructivo?token={tok}&amp;doc={d.clave}'>"
            f"{html.escape(d.pestana)}</a>"
        )
    cuerpo.append("</nav>")
    cuerpo.append(f"<section><h2>{md.en_linea(titulo)}</h2>")
    cuerpo.append(f"<p class=ayuda>{html.escape(doc.para_que)}</p>")
    if intro:
        cuerpo.append(f"<div class=md>{a_html(intro)}</div>")
    cuerpo.append(
        "<div class=herramientas><input id=q type=search "
        "placeholder='Buscar en este documento (ej.: talla, Chatwoot, abono)…'>"
        "<button id=abrir type=button>Abrir todo</button>"
        "<button id=cerrar type=button>Cerrar todo</button></div>"
        "<div id=cuenta class=cuenta></div></section>"
    )
    cuerpo.append("<nav class=indice>")
    for s in secciones:
        cuerpo.append(f"<a href='#{s.ancla}'>{md.en_linea(s.titulo)}</a>")
    cuerpo.append("</nav>")
    for s in secciones:
        cuerpo.append(
            f"<details class=sec id='{s.ancla}'><summary>{md.en_linea(s.titulo)}"
            f"</summary><div class=md>{a_html(s.cuerpo)}</div></details>"
        )
    fuentes = ", ".join(
        str(p.relative_to(RAIZ)).replace("\\", "/") for p in _archivos(doc)
    )
    cuerpo.append(
        "<p class=de-donde>Esta página se arma con "
        f"<code>{html.escape(fuentes)}</code> del proyecto: cuando se actualiza el "
        "documento, aquí se ve solo con el próximo despliegue.</p>"
    )
    cuerpo.append("</main>" + _JS + "</body></html>")
    return "".join(cuerpo)
