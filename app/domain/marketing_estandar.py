"""El estándar de la carpeta de marketing: qué archivos, qué columnas, qué reglas (01/10).

Camilo, 01/10: «deja estandarizado el proceso; el otro chat que hace mis
campañas debe seguir tus reglas para que pueda subir todo SIN IA, solo con el
doble clic; si sale un cambio, que lo reporte en un .md».

Este módulo ES el estándar. De aquí salen tres cosas, para que nunca se
desalineen:

1. La revisión que corre al subir (`revisar`): ERRORES que bloquean la
   subida (falta el tablero, una tabla sin sus columnas obligatorias) y AVISOS
   que la dejan pasar (un valor mal escrito, una tabla que el panel no
   conoce, un estado de tarea que no existe…).
2. El documento `ESTANDAR-DEL-PANEL.md` que lee el Claude de marketing
   (`documento()`), con una prueba que falla si el de `externos/marketing/`
   no es el que sale de aquí.
3. Las plantillas de las tablas (`plantilla()`): la cabecera exacta.

Cambiar el estándar = cambiar `ESQUEMAS` (y subir `VERSION`), regenerar el
documento y las plantillas (`python scripts/marketing.py --estandar`) y
contárselo al Claude de marketing.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

#: Sube cuando cambia algo que el Claude de marketing tiene que saber.
VERSION = 2

#: Tipos de columna: cómo se escribe cada valor.
TIPOS = {
    "mes": "AAAA-MM (ej.: 2026-09)",
    "fecha": "AAAA-MM-DD (ej.: 2026-10-05)",
    "pesos": "pesos colombianos, entero, sin $ ni puntos (ej.: 1469)",
    "entero": "número entero (ej.: 52)",
    "decimal": "número con punto decimal (ej.: 1.51)",
    "pct": "porcentaje como número, sin % (ej.: 4.7)",
    "texto": "texto libre",
    "enlace": "dirección https:// completa",
    "si_no": "si o no",
}


@dataclass(frozen=True)
class Columna:
    nombre: str
    tipo: str
    obligatoria: bool = False
    que_es: str = ""


@dataclass(frozen=True)
class Tabla:
    archivo: str  # dentro de `datos/`
    para_que: str
    columnas: tuple[Columna, ...]
    #: Dónde la usa el panel (para que el Claude de marketing sepa qué cambia).
    se_ve_en: str = ""
    #: True = ya existe en la carpeta con datos; False = plantilla nueva.
    con_datos: bool = False
    #: Columnas con prefijo variable (ej.: «vistas_al_2026-09-30»).
    prefijos: tuple[str, ...] = field(default_factory=tuple)

    @property
    def obligatorias(self) -> tuple[str, ...]:
        return tuple(c.nombre for c in self.columnas if c.obligatoria)


def _c(nombre: str, tipo: str, que_es: str = "", obligatoria: bool = False) -> Columna:
    return Columna(nombre, tipo, obligatoria, que_es)


#: Las tablas que entiende el panel. El orden es el del documento.
ESQUEMAS: tuple[Tabla, ...] = (
    Tabla(
        "ventas_mensuales.csv",
        "Lo vendido y lo gastado en pauta, mes a mes (de las ventas de Camilo)",
        (
            _c("mes", "mes", "El mes. La última fila puede ser «TOTAL»", True),
            _c("anillos_vendidos", "entero", "Anillos vendidos ese mes", True),
            _c("ingresos_cop", "pesos", "Lo que pagaron las clientas", True),
            _c("gasto_pauta_cop", "pesos", "Lo gastado en Meta ese mes", True),
            _c("conversaciones", "entero", "Conversaciones iniciadas (de Meta)"),
            _c("tasa_cierre_pct", "pct", "Anillos ÷ conversaciones × 100"),
            _c("costo_por_venta_cop", "pesos", "Pauta ÷ anillos"),
            _c("roas", "decimal", "Ventas ÷ pauta"),
            _c("costo_anillos_cop", "pesos", "Costo de fabricar los anillos vendidos"),
            _c("ganancia_despues_de_pauta_cop", "pesos", "Ventas − costo − pauta"),
            _c("fuente", "texto", "De dónde salen los números"),
            _c("notas", "texto"),
        ),
        "Números (indicadores del mes, embudo, historia) y Estrategia (recomendaciones)",
        True,
    ),
    Tabla(
        "meta_mensual.csv",
        "La cuenta de Meta Ads, mes a mes (Ads Manager, toda la cuenta)",
        (
            _c("mes", "mes", obligatoria=True),
            _c("gasto_cop", "pesos", "Importe gastado", True),
            _c("impresiones", "entero"),
            _c("alcance", "entero", "Personas distintas"),
            _c("frecuencia", "decimal", "Impresiones ÷ alcance"),
            _c("cpm_cop", "pesos", "Costo de 1.000 impresiones"),
            _c("conversaciones_iniciadas", "entero"),
            _c("costo_por_conversacion_cop", "pesos"),
        ),
        "Números (indicadores, embudo, historia) y Estrategia",
        True,
    ),
    Tabla(
        "meta_campanas_mensual.csv",
        "Cada campaña, mes a mes. También llena la hoja Publicidad del ERP",
        (
            _c("mes", "mes", obligatoria=True),
            _c("campana", "texto", "El nombre en Ads Manager", True),
            _c("objetivo", "texto", "mensajes · ventas · visitas al perfil · …", True),
            _c("gasto_cop", "pesos", obligatoria=True),
            _c("alcance", "entero"),
            _c("frecuencia", "decimal"),
            _c("cpm_cop", "pesos"),
            _c("conversaciones_iniciadas", "entero"),
            _c("costo_por_conversacion_cop", "pesos"),
        ),
        "Campañas, Estrategia (alerta de «visitas al perfil») y el ERP (hoja Publicidad)",
        True,
    ),
    Tabla(
        "meta_anuncios_mensual.csv",
        "Cada anuncio, mes a mes",
        (
            _c("mes", "mes", obligatoria=True),
            _c("anuncio", "texto", "El nombre en Ads Manager", True),
            _c("video", "texto", "Qué video o producción usa"),
            _c("gasto_cop", "pesos", obligatoria=True),
            _c("alcance", "entero"),
            _c("frecuencia", "decimal"),
            _c("cpm_cop", "pesos"),
            _c("conversaciones_iniciadas", "entero"),
            _c("costo_por_conversacion_cop", "pesos"),
        ),
        "Campañas (ranking de anuncios)",
        True,
    ),
    Tabla(
        "creativos.csv",
        "Cada video, carrusel o historia que se ha pautado o se puede pautar",
        (
            _c("creativo_id", "texto", "Un código corto y fijo (ej.: CUARTA)", True),
            _c("nombre", "texto", obligatoria=True),
            _c("tipo", "texto", "reel · carrusel · historia · reel de clienta · …", True),
            _c("enlace", "texto", "La publicación en Instagram"),
            _c("publicado", "texto", "AAAA-MM-DD o AAAA-MM"),
            _c("duracion_s", "entero"),
            _c("me_gusta", "entero"),
            _c("comentarios", "entero"),
            _c("descripcion", "texto"),
            _c("anuncios_que_lo_usaron", "texto"),
            _c("en_pauta", "texto", "Meses en que se pautó"),
            _c("gasto_total_cop", "pesos"),
            _c("costo_mes_1_cop", "pesos", "Costo por conversación el primer mes"),
            _c("costo_ultimo_mes_cop", "pesos"),
            _c("notas", "texto"),
        ),
        "Creativos (producciones) e Indicadores (días del video más nuevo)",
        True,
        ("vistas",),
    ),
    # --- Plantillas: lo que usan las empresas de marketing, a la medida de Lía ---
    Tabla(
        "semanal.csv",
        "La cuenta de CADA LUNES (tarea de los lunes): una fila por semana",
        (
            _c("semana", "fecha", "El lunes de esa semana", True),
            _c("gasto_cop", "pesos", "Importe gastado en la semana (Ads Manager)", True),
            _c("anillos", "entero", "Anillos vendidos (abono pagado) en la semana", True),
            _c("conversaciones", "entero", "Conversaciones iniciadas en la semana"),
            _c("ventas_cop", "pesos", "Lo vendido en la semana"),
            _c(
                "anillos_bog_med_cali",
                "entero",
                "De esos, cuántos de Bogotá, Medellín o Cali",
            ),
            _c("anillos_resto", "entero", "Y cuántos del resto del país"),
            _c("decision", "texto", "Qué se hizo según el semáforo"),
            _c("notas", "texto"),
        ),
        "Hoy (el semáforo de la semana) y Números (semana a semana)",
    ),
    Tabla(
        "presupuesto.csv",
        "El tope y el ritmo de cada mes (el freno contra gastar sin vender)",
        (
            _c("mes", "mes", obligatoria=True),
            _c("tope_cop", "pesos", "El límite de la cuenta ese mes", True),
            _c("diario_cop", "pesos", "Presupuesto diario planeado"),
            _c("notas", "texto"),
        ),
        "Números (cuánto del tope se ha gastado)",
    ),
    Tabla(
        "organico.csv",
        "El Instagram sin pauta, mes a mes (Panel profesional del perfil)",
        (
            _c("mes", "mes", obligatoria=True),
            _c("seguidores", "entero", "Al cierre del mes", True),
            _c("alcance_cuenta", "entero", "Cuentas alcanzadas"),
            _c("visitas_perfil", "entero"),
            _c("clics_enlace", "entero", "Toques al enlace de WhatsApp"),
            _c("reels_publicados", "entero"),
            _c("interacciones", "entero"),
        ),
        "Números (orgánico) e Indicadores",
    ),
    Tabla(
        "contenido.csv",
        "Cada publicación orgánica y cómo le fue (para encontrar el próximo anuncio)",
        (
            _c("fecha", "fecha", obligatoria=True),
            _c("tipo", "texto", "reel · carrusel · historia · post", True),
            _c("tema", "texto", "De qué trata (gancho, ángulo)", True),
            _c("enlace", "texto"),
            _c("vistas", "entero"),
            _c("guardados", "entero"),
            _c("compartidos", "entero"),
            _c("comentarios", "entero"),
            _c("candidato_a_anuncio", "si_no", "Si pasó de 20 mil vistas en 48 h"),
        ),
        "Creativos (contenido orgánico)",
    ),
    Tabla(
        "competencia.csv",
        "Lo que pauta la competencia (Biblioteca de anuncios de Meta, una vez al mes)",
        (
            _c("fecha", "fecha", obligatoria=True),
            _c("marca", "texto", obligatoria=True),
            _c("producto", "texto", obligatoria=True),
            _c("precio_cop", "pesos"),
            _c("oferta", "texto", "2x1, envío gratis, contraentrega…"),
            _c("enlace", "texto"),
            _c("notas", "texto"),
        ),
        "Creativos (competencia)",
    ),
    Tabla(
        "clientas.csv",
        "Las clientas en números, mes a mes (SOLO totales: nada de nombres ni celulares)",
        (
            _c("mes", "mes", obligatoria=True),
            _c("clientas_nuevas", "entero", obligatoria=True),
            _c("recompras", "entero", "Clientas que ya habían comprado antes"),
            _c("nps_promedio", "decimal", "Del 0 al 10, a quienes contestaron"),
            _c("respuestas_nps", "entero"),
            _c("resenas", "entero", "Reseñas o testimonios recibidos"),
            _c("fotos_recibidas", "entero", "Fotos o videos de clientas con su anillo"),
        ),
        "Números (clientas) e Indicadores (recompra, satisfacción)",
    ),
    Tabla(
        "ciudades.csv",
        "Ventas por ciudad, mes a mes (mientras el bot no tenga pedidos reales)",
        (
            _c("mes", "mes", obligatoria=True),
            _c("ciudad", "texto", obligatoria=True),
            _c("anillos", "entero", obligatoria=True),
            _c("ventas_cop", "pesos"),
        ),
        "Números (ciudades) y la prueba «Resto de Colombia»",
    ),
    # --- Las campañas piloto (03/10): pestaña «Piloto» -----------------------
    # Lo que pasa DENTRO del chat (conversaciones, enganchadas, listas para
    # pagar, ventas) lo cuenta el bot solo; aquí va lo que solo sabe Meta.
    Tabla(
        "piloto_fases.csv",
        "Las fases de cada campaña piloto: fechas, presupuesto y cuándo se pasa",
        (
            _c("campana", "texto", "Nombre de la campaña (ej.: PILOTO VENTABOT)", True),
            _c("fase", "entero", "1, 2, 3…", True),
            _c("nombre", "texto", "Lanzamiento, Validación, Escala…", True),
            _c("desde", "fecha", "Primer día de la fase", True),
            _c("hasta", "fecha", "Último día con pauta (vacío = abierta)"),
            _c("diario_cop", "pesos", "Presupuesto diario de la fase"),
            _c("conjuntos", "texto", "Qué conjuntos de anuncios corren"),
            _c("pasa_si", "texto", "Cuándo se pasa a la siguiente fase"),
            _c("documento", "texto", "El plan completo (ej.: PILOTO-VENTABOT.md)"),
        ),
        "Piloto (la fase de hoy, el filtro por fase y el plan)",
    ),
    Tabla(
        "piloto_dias.csv",
        "Lo que dice Ads Manager del piloto, una fila por día (solo totales)",
        (
            _c("fecha", "fecha", obligatoria=True),
            _c("campana", "texto", "La misma de piloto_fases.csv", True),
            _c("gasto_cop", "pesos", "Importe gastado ese día", True),
            _c("impresiones", "entero"),
            _c("reproducciones_3s", "entero", "Para la retención a 3 s"),
            _c("conversaciones_meta", "entero", "Conversaciones que cuenta Meta"),
            _c("notas", "texto"),
        ),
        "Piloto (la calificación, el embudo y la tabla día a día; lo del chat lo "
        "pone el bot)",
    ),
    Tabla(
        "piloto_anuncios.csv",
        "Cada anuncio del piloto, una fila por anuncio y por semana",
        (
            _c("semana", "fecha", "El primer día de esa semana del piloto", True),
            _c("campana", "texto", obligatoria=True),
            _c("anuncio", "texto", "A, B, C… o su nombre", True),
            _c("gasto_cop", "pesos", obligatoria=True),
            _c("dias_en_pauta", "entero", "Días que lleva prendido"),
            _c("retencion_3s_pct", "pct", "Reproducciones de 3 s ÷ impresiones × 100"),
            _c("conversaciones", "entero", "Las de Meta para ese anuncio", True),
            _c("enganchadas", "entero", "Si hay atribución por anuncio"),
            _c("ventas", "entero", "Si hay atribución por anuncio"),
            _c("notas", "texto"),
        ),
        "Piloto (la calificación de cada anuncio y cuál apagar)",
    ),
)

POR_ARCHIVO = {t.archivo: t for t in ESQUEMAS}

#: Los documentos con un papel fijo. Los demás .md son libres (van a Biblioteca).
DOCUMENTOS = {
    "PARA-EL-PANEL.md": "El tablero (obligatorio): lo que Lía ve primero",
    "PEDIDOS-AL-PANEL.md": "Los cambios que el marketing necesita en el panel (ver "
    "abajo)",
    "ESTANDAR-DEL-PANEL.md": "Este documento (lo pone el lanzador; no editarlo)",
}

#: Los valores cerrados del tablero (formato lia-marketing-panel v3).
VALORES_CERRADOS = {
    ("alertas", "nivel"): ("urgente", "aviso"),
    ("tareas", "estado"): ("pendiente", "en_curso", "hecho", "descartado"),
    ("tareas", "cuando"): (
        "hoy",
        "esta_semana",
        "cada_lunes",
        "con_cada_entrega",
        "decision",
        "este_mes",
    ),
    ("tareas", "quien"): ("lia", "camilo", "ambos"),
    ("cifras", "tono"): ("bueno", "malo", "neutro"),
    ("pruebas", "estado"): (
        "por_lanzar",
        "corriendo",
        "terminada",
        "en_cola",
        "descartada",
    ),
    ("reels", "estado"): (
        "en_pauta",
        "gastado",
        "de_reserva",
        "pedir_permiso",
        "retirado",
    ),
    ("aprendizajes", "confianza"): ("baja", "media", "alta"),
}


# ---------------------------------------------------------------------------
# La revisión
# ---------------------------------------------------------------------------


@dataclass
class Informe:
    """Lo que encontró la revisión. Con errores, la carpeta no se sube."""

    errores: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    tablas_conocidas: list[str] = field(default_factory=list)
    tablas_desconocidas: list[str] = field(default_factory=list)
    plantillas_vacias: list[str] = field(default_factory=list)
    pedidos_pendientes: list[str] = field(default_factory=list)
    version_del_estandar_en_la_carpeta: int | None = None

    @property
    def ok(self) -> bool:
        return not self.errores

    def como_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_FECHA = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def valor_valido(tipo: str, valor: str) -> bool:
    """Si un valor (no vacío) está escrito como pide su tipo."""
    v = valor.strip()
    if tipo == "mes":
        return bool(_MES.match(v))
    if tipo == "fecha":
        return bool(_FECHA.match(v))
    if tipo in ("pesos", "entero"):
        return bool(re.fullmatch(r"-?\d+", v))
    if tipo in ("decimal", "pct"):
        return bool(re.fullmatch(r"-?\d+(\.\d+)?", v))
    if tipo == "enlace":
        return v.startswith("https://")
    if tipo == "si_no":
        return v.lower() in ("si", "sí", "no")
    return True


def revisar_tabla(archivo: str, texto: str, informe: Informe) -> None:
    esquema = POR_ARCHIVO.get(archivo)
    if esquema is None:
        informe.tablas_desconocidas.append(archivo)
        informe.avisos.append(
            f"datos/{archivo}: el panel no conoce esta tabla; sale en Biblioteca pero no "
            "en los cálculos. Si hace falta, pídelo en PEDIDOS-AL-PANEL.md."
        )
        return
    lector = csv.DictReader(io.StringIO(texto.lstrip("\ufeff")))
    cabecera = [c.strip() for c in (lector.fieldnames or [])]
    faltan = [c for c in esquema.obligatorias if c not in cabecera]
    if faltan:
        informe.errores.append(
            f"datos/{archivo}: faltan las columnas obligatorias {', '.join(faltan)}"
        )
        return
    informe.tablas_conocidas.append(archivo)
    conocidas = {c.nombre for c in esquema.columnas}
    for c in cabecera:
        if c not in conocidas and not (
            esquema.prefijos and c.startswith(esquema.prefijos)
        ):
            informe.avisos.append(
                f"datos/{archivo}: la columna «{c}» no está en el estándar (se muestra, "
                "no se usa en los cálculos)"
            )
    filas = list(lector)
    if not filas:
        informe.plantillas_vacias.append(archivo)
        return
    tipos = {c.nombre: c.tipo for c in esquema.columnas}
    malos: dict[str, list[int]] = {}
    for n, fila in enumerate(filas, start=2):
        for col, valor in fila.items():
            col = (col or "").strip()
            valor = (valor or "").strip()
            if not valor or col not in tipos:
                continue
            if col == "mes" and valor.upper() == "TOTAL":
                continue
            if not valor_valido(tipos[col], valor):
                malos.setdefault(col, []).append(n)
        for col in esquema.obligatorias:
            if not (fila.get(col) or "").strip():
                malos.setdefault(f"{col} (vacía)", []).append(n)
    for col, lineas in malos.items():
        nombre = col.split(" ")[0]
        como = TIPOS.get(tipos.get(nombre, ""), "")
        informe.avisos.append(
            f"datos/{archivo}: «{col}» mal escrita en la(s) línea(s) "
            f"{', '.join(map(str, lineas[:8]))}{'…' if len(lineas) > 8 else ''}"
            + (f" — va como {como}" if como else "")
        )


def revisar_tablero(datos: dict, informe: Informe) -> None:
    for (clave, campo), validos in VALORES_CERRADOS.items():
        for i, x in enumerate(datos.get(clave) or [], start=1):
            if isinstance(x, dict) and x.get(campo) and x.get(campo) not in validos:
                ident = x.get("id") or f"#{i}"
                informe.avisos.append(
                    f"PARA-EL-PANEL.md: {clave} {ident} tiene {campo} «{x.get(campo)}»; "
                    f"vale uno de: {', '.join(validos)}"
                )


_PEDIDO = re.compile(r"^##\s+(.*?)\s*·\s*(pendiente|hecho|descartado)\s*$", re.IGNORECASE)


def pedidos_pendientes(texto: str) -> list[str]:
    """Los títulos de los pedidos con estado «pendiente» en PEDIDOS-AL-PANEL.md."""
    return [
        m.group(1)
        for linea in (texto or "").splitlines()
        if (m := _PEDIDO.match(linea.strip())) and m.group(2).lower() == "pendiente"
    ]


def version_del_documento(texto: str) -> int | None:
    m = re.search(r"^version_estandar:\s*(\d+)\s*$", texto or "", re.MULTILINE)
    return int(m.group(1)) if m else None


def revisar(archivos: dict[str, str], datos_del_tablero: dict | None) -> Informe:
    """La carpeta entera ({ruta: texto}). El tablero ya viene leído (o None)."""
    informe = Informe()
    if datos_del_tablero is None:
        informe.errores.append("falta PARA-EL-PANEL.md, o no se puede leer")
    else:
        revisar_tablero(datos_del_tablero, informe)
    for ruta, texto in sorted(archivos.items()):
        if ruta.startswith("datos/") and ruta.endswith(".csv") and ruta.count("/") == 1:
            revisar_tabla(ruta.removeprefix("datos/"), texto, informe)
        elif ruta.endswith(".csv"):
            informe.avisos.append(
                f"{ruta}: las tablas van en datos/ (esta sale en Biblioteca, sin "
                "cálculos)"
            )
    if "PEDIDOS-AL-PANEL.md" in archivos:
        informe.pedidos_pendientes = pedidos_pendientes(archivos["PEDIDOS-AL-PANEL.md"])
    else:
        informe.avisos.append(
            "no está PEDIDOS-AL-PANEL.md: es donde se piden los cambios al panel"
        )
    version = version_del_documento(archivos.get("ESTANDAR-DEL-PANEL.md", ""))
    informe.version_del_estandar_en_la_carpeta = version
    if version is not None and version < VERSION:
        informe.avisos.append(
            f"ESTANDAR-DEL-PANEL.md es la versión {version} y el panel va en la "
            f"{VERSION}: "
            "léelo de nuevo (el lanzador lo actualiza)"
        )
    for t in ESQUEMAS:
        if t.con_datos and f"datos/{t.archivo}" not in archivos:
            informe.avisos.append(
                f"no está datos/{t.archivo}: el panel la usa ({t.se_ve_en})"
            )
    return informe


# ---------------------------------------------------------------------------
# Lo que se genera: plantillas y el documento
# ---------------------------------------------------------------------------


def plantilla(tabla: Tabla) -> str:
    """La cabecera exacta de la tabla, lista para llenar."""
    return ",".join(c.nombre for c in tabla.columnas) + "\n"


PEDIDOS_EJEMPLO = """\
# Pedidos al panel de marketing

Aquí el Claude de marketing pide los cambios que necesita en el panel (una tabla
nueva, una columna, una sección, un cálculo). Camilo se los pasa al Claude de
VentaBot, que cambia el panel y marca el pedido como hecho.

Formato fijo (el panel cuenta los pendientes): un título `##` con el nombre del
pedido, un punto medio y el estado (`pendiente`, `hecho` o `descartado`), y
debajo qué, por qué y un ejemplo.

## Ejemplo: tabla de ventas por anuncio · descartado

- **Fecha:** 2026-10-01
- **Qué:** una tabla `datos/ventas_por_anuncio.csv` (mes, anuncio, anillos).
- **Por qué:** para el costo por venta de cada anuncio.
- **Ejemplo de fila:** `2026-10,REEL lila,12`
- **Respuesta del panel:** lo hará VentaBot solo con la atribución (ADR 0028).
"""


def documento() -> str:
    """`ESTANDAR-DEL-PANEL.md`, generado de este módulo. No se edita a mano."""
    lineas = [
        "---",
        f"version_estandar: {VERSION}",
        "lo_genera: ventabot (scripts/marketing.py --estandar) · no editar a mano",
        "---",
        "",
        "# El estándar de la carpeta de marketing para el panel",
        "",
        "Esta carpeta se sube al panel de Lía (`https://bot.lunajoyas.example/panel/"
        "marketing`) con un **doble clic en `SUBIR-AL-PANEL.cmd`**, sin IA de por medio. "
        "Para que eso funcione siempre, todo lo de aquí sigue este estándar. Al subir, "
        "el servidor lo revisa: los **errores** bloquean la subida (y dicen qué "
        "arreglar); los **avisos** la dejan pasar y se ven en el panel (Biblioteca → "
        "Calidad de los datos).",
        "",
        "## 1. Cómo se sube",
        "",
        "1. Actualiza los archivos (el tablero sube `revision` y `actualizado`).",
        "2. Doble clic en `SUBIR-AL-PANEL.cmd` (en esta carpeta; o "
        "`SUBIR-AL-PANEL.cmd --sin-pausa` desde un programa). Desde Git Bash también: "
        "`tar -czf - --exclude=./datos/entrada --exclude=./CLAUDE.md --exclude=./.git . "
        '| ssh servidor-demo "cd ~/ventabot && sudo docker compose exec -T ventabot '
        'python scripts/marketing.py --instalar -"`.',
        "3. Lee lo que responde: `✔` subió (con los avisos, si hay); `✘` no subió y "
        "dice por qué.",
        "",
        "Se sube TODO: los `.md` (cualquier carpeta) y las tablas `datos/*.csv`. **No** "
        "se suben `CLAUDE.md` (instrucciones para Claude) ni `datos/entrada/` "
        "(exportes crudos). Ningún otro tipo de archivo pasa. Tope: 2 MB por archivo.",
        "",
        "## 2. Reglas que bloquean (errores)",
        "",
        "- Falta `PARA-EL-PANEL.md`, o su bloque JSON no se lee (formato "
        "`lia-marketing-panel`; las marcas `<!-- DATOS:INICIO -->` y "
        "`<!-- DATOS:FIN -->` SOLAS en su renglón).",
        "- La `revision` es más vieja que la que ya está puesta.",
        "- Una tabla conocida (§4) no tiene alguna de sus columnas obligatorias.",
        "- Un archivo no está en UTF-8.",
        "",
        "## 3. Reglas que avisan (pasan, pero se arreglan)",
        "",
        "- Un valor mal escrito para su tipo (se salta en los cálculos).",
        "- Una columna o una tabla que el panel no conoce (se muestra en Biblioteca, sin "
        "cálculos). Si hace falta, se pide en `PEDIDOS-AL-PANEL.md`.",
        "- Un valor cerrado del tablero que no existe (ej.: un estado de tarea).",
        "- Falta una tabla que el panel usa, o falta `PEDIDOS-AL-PANEL.md`.",
        "",
        "Cómo se escribe cada tipo:",
        "",
        "| Tipo | Se escribe |",
        "|---|---|",
        *(f"| `{k}` | {v} |" for k, v in TIPOS.items()),
        "",
        "Nada de datos personales de clientas (nombres, celulares, direcciones): solo "
        "totales.",
        "",
        "## 4. Las tablas (`datos/`)",
        "",
        "Las que dicen **plantilla** aún no tienen datos: su cabecera está lista en "
        "`datos/` y el panel las muestra en cuanto tengan filas. Las columnas en "
        "**negrita** son obligatorias; el orden de las columnas no importa.",
        "",
    ]
    for t in ESQUEMAS:
        estado = "con datos" if t.con_datos else "plantilla"
        lineas += [
            f"### `datos/{t.archivo}` · {estado}",
            "",
            f"{t.para_que}. Se ve en: {t.se_ve_en}.",
            "",
            "| Columna | Tipo | Qué es |",
            "|---|---|---|",
            *(
                f"| {'**' + c.nombre + '**' if c.obligatoria else c.nombre} | "
                f"`{c.tipo}` | {c.que_es} |"
                for c in t.columnas
            ),
        ]
        if t.prefijos:
            lineas.append(
                f"| {', '.join(p + '_…' for p in t.prefijos)} | `entero` | Columnas "
                "con fecha en el nombre (ej.: vistas_al_2026-09-30) |"
            )
        lineas.append("")
    lineas += [
        "## 5. Los documentos",
        "",
        *(f"- `{k}`: {v}." for k, v in DOCUMENTOS.items()),
        "- Cualquier otro `.md` (en la raíz o en carpetas como `creativos/`, "
        "`experimentos/`, `bitacora/`) sale tal cual en Biblioteca; los de nombre "
        "conocido (ESTADO, PLAN-CAMPANA, CAMPANA-OCTUBRE, APRENDIZAJES, PENDIENTES, "
        "negocio, cuenta-instagram, creativos/…) también en su pestaña.",
        "",
        "## 6. Cómo pedir un cambio al panel",
        "",
        "Si el marketing necesita algo que el panel no tiene (una tabla, una columna, un "
        "cálculo, una sección), **no se inventa un formato**: se pide en "
        "`PEDIDOS-AL-PANEL.md`, con este formato (el panel cuenta los pendientes y "
        "Camilo se los pasa al Claude de VentaBot):",
        "",
        "```",
        "## Nombre corto del pedido · pendiente",
        "- **Fecha:** AAAA-MM-DD",
        "- **Qué:** …",
        "- **Por qué:** …",
        "- **Ejemplo:** …",
        "```",
        "",
        "Cuando VentaBot lo haga, sube la `VERSION` de este estándar si cambió algo y el "
        "pedido pasa a `· hecho`.",
        "",
    ]
    return "\n".join(lineas)
