"""`marketing` — poner una revisión nueva del marketing en el panel.

Para qué sirve
==============
El Claude de marketing lleva la carpeta `Documents\\GitHub\\marketing-lia`: el tablero
`PARA-EL-PANEL.md`, los documentos (plan, estado, aprendizajes, creativos,
bitácora…) y las tablas `datos/*.csv`. El panel muestra TODO eso en
`/panel/marketing`. Este script es la puerta de entrada al servidor, y lo
llama `SUBIR-MARKETING.cmd` (doble clic en el PC):

    python scripts/marketing.py                 qué revisión está puesta
    python scripts/marketing.py --instalar -    poner lo que llega por la entrada
    python scripts/marketing.py --instalar RUTA poner ese archivo

Lo que llega puede ser la CARPETA en un .tar.gz (lo normal: `SUBIR-MARKETING`
la empaqueta) o solo `PARA-EL-PANEL.md` (se cambia ese y lo demás queda).

Antes de reemplazar nada lo LEE con el mismo lector del panel: un tablero con
el JSON roto no llega a la pantalla de Lía, y el motivo sale aquí, en claro.
Tampoco deja poner una revisión MÁS VIEJA que la que hay. Del paquete solo
pasan `.md` y `.csv` (ni `CLAUDE.md`, que son instrucciones para Claude, ni
`datos/entrada/`, que son exportes crudos). La carpeta anterior queda al lado
(`carpeta.anterior`).
"""

from __future__ import annotations

import argparse
import io
import re
import shutil
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infra.consola import preparar_salida

# UTF-8 pase lo que pase: sin esto, redirigir la salida a un archivo (o
# leerla desde otro proceso) revienta en Windows al imprimir un ✔.
preparar_salida()


from app.domain import marketing_estandar as estandar
from app.domain.marketing import Tablero, leer_tablero
from app.infra.settings import get_settings

TABLERO = "PARA-EL-PANEL.md"
#: Lo único que pasa del paquete: documentos y tablas, con rutas sencillas.
PERMITIDO = re.compile(r"^(?:[\w\-]+/)*[\w\-.]+\.(?:md|csv)$")
FUERA = ("CLAUDE.md",)
CARPETAS_FUERA = ("datos/entrada/", ".git/")
#: Topes de tamaño: la carpeta real pesa ~150 KB.
TOPE_POR_ARCHIVO = 2_000_000
TOPE_TOTAL = 15_000_000


def instalada(carpeta: Path) -> Tablero | None:
    """La revisión puesta ahora, o None si no hay ninguna (o no se lee)."""
    try:
        return leer_tablero((carpeta / TABLERO).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def archivos_del_paquete(datos: bytes) -> dict[str, bytes]:
    """{ruta: contenido} de lo que pasa del .tar.gz. ValueError si no sirve."""
    archivos: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(datos), mode="r:gz") as paquete:
            for m in paquete.getmembers():
                nombre = m.name.replace("\\", "/").removeprefix("./")
                if (
                    not m.isfile()
                    or nombre in FUERA
                    or nombre.startswith(CARPETAS_FUERA)
                    or ".." in nombre.split("/")
                    or not PERMITIDO.match(nombre)
                ):
                    continue
                if m.size > TOPE_POR_ARCHIVO:
                    raise ValueError(f"«{nombre}» pesa demasiado ({m.size:,} bytes)")
                contenido = paquete.extractfile(m)
                if contenido is not None:
                    archivos[nombre] = contenido.read()
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ValueError(f"el paquete no se puede abrir ({exc})") from exc
    if sum(len(v) for v in archivos.values()) > TOPE_TOTAL:
        raise ValueError("el paquete pesa demasiado")
    return archivos


def instalar(
    datos: bytes, carpeta: Path
) -> tuple[Tablero, dict[str, bytes], estandar.Informe]:
    """Pone la revisión. ValueError si no se puede, con el motivo en claro."""
    if datos[:2] == b"\x1f\x8b":
        archivos = archivos_del_paquete(datos)
        if TABLERO not in archivos:
            raise ValueError(f"el paquete no trae {TABLERO}")
    else:
        # Solo el tablero: lo demás de la carpeta se queda como está.
        archivos = (
            {
                p.relative_to(carpeta).as_posix(): p.read_bytes()
                for p in carpeta.rglob("*")
                if p.is_file()
            }
            if carpeta.is_dir()
            else {}
        )
        archivos[TABLERO] = datos
    for nombre, contenido in archivos.items():
        try:
            contenido.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"«{nombre}» no está en UTF-8") from exc

    nuevo = leer_tablero(archivos[TABLERO].decode("utf-8-sig"))
    actual = instalada(carpeta)
    if actual is not None and nuevo.revision < actual.revision:
        raise ValueError(
            f"es la revisión {nuevo.revision} y ya está puesta la {actual.revision}: "
            "no se vuelve atrás (si es a propósito, súbele el número de revisión)"
        )
    informe = estandar.revisar(
        {n: c.decode("utf-8-sig") for n, c in archivos.items()}, nuevo.datos
    )
    if informe.errores:
        raise ValueError(
            "no cumple el estándar (ESTANDAR-DEL-PANEL.md):\n      · "
            + "\n      · ".join(informe.errores)
        )

    # Primero se arma la nueva aparte: si algo falla a mitad, la que está
    # puesta sigue intacta. Después se rota: puesta → anterior, nueva → puesta.
    subiendo = carpeta.with_name(carpeta.name + ".subiendo")
    anterior = carpeta.with_name(carpeta.name + ".anterior")
    shutil.rmtree(subiendo, ignore_errors=True)
    for nombre, contenido in archivos.items():
        destino = subiendo / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
    if carpeta.exists():
        shutil.rmtree(anterior, ignore_errors=True)
        carpeta.replace(anterior)
    subiendo.replace(carpeta)

    # La fase 1 (30/09) guardaba solo el tablero suelto, un nivel más arriba.
    for viejo in ("PARA-EL-PANEL.md", "PARA-EL-PANEL.anterior.md"):
        (carpeta.parent / viejo).unlink(missing_ok=True)
    return nuevo, archivos, informe


def describir(t: Tablero, archivos: dict[str, bytes] | None = None) -> str:
    datos = t.datos
    tareas = [x for x in datos.get("tareas") or [] if isinstance(x, dict)]
    abiertas = sum(1 for x in tareas if x.get("estado") not in ("hecho", "descartado"))
    texto = (
        f"revisión {t.revision} del {t.actualizado:%d/%m/%Y} · formato "
        f"v{t.version_formato} · {abiertas} tarea(s) abierta(s) de {len(tareas)} · "
        f"{len(datos.get('alertas') or [])} alerta(s)"
    )
    if archivos:
        docs = sum(1 for n in archivos if n.endswith(".md"))
        tablas = sum(1 for n in archivos if n.endswith(".csv"))
        texto += f" · {docs} documento(s) y {tablas} tabla(s)"
    return texto


def actualizar_erp(carpeta: Path) -> str:
    """Pauta → hoja Publicidad, la hoja de ciudades y la foto para el panel.

    Devuelve qué pasó, en una línea. Nunca lanza: la carpeta ya quedó puesta.
    """
    from app.adapters.erp.marketing import actualizar
    from app.adapters.erp.sheets import SheetsDeGoogle

    s = get_settings()
    if not (s.sheets_spreadsheet_id and s.google_service_account_json):
        return "sin ERP configurado (falta la hoja o la credencial)"
    try:
        hoja = SheetsDeGoogle(s.sheets_spreadsheet_id, s.google_service_account_json)
        campanas = carpeta / "datos" / "meta_campanas_mensual.csv"
        texto = campanas.read_text(encoding="utf-8-sig") if campanas.is_file() else ""
        return actualizar(hoja, texto, s.marketing_foto_del_erp)
    except Exception as exc:  # el ERP nunca tumba la subida
        return f"no se pudo ({exc.__class__.__name__}: {exc})"


def generar_estandar(destino: Path) -> list[str]:
    """El documento del estándar, las plantillas y los pedidos en `destino`.

    El documento se reescribe siempre (lo genera este código). Las tablas y
    PEDIDOS-AL-PANEL.md solo se crean si NO existen: nunca se pisan datos.
    """
    hechos = []
    (destino / "datos").mkdir(parents=True, exist_ok=True)
    doc = destino / "ESTANDAR-DEL-PANEL.md"
    doc.write_text(estandar.documento(), encoding="utf-8")
    hechos.append(doc.name)
    for t in estandar.ESQUEMAS:
        tabla = destino / "datos" / t.archivo
        if not tabla.exists():
            tabla.write_text(estandar.plantilla(t), encoding="utf-8")
            hechos.append(f"datos/{t.archivo}")
    pedidos = destino / "PEDIDOS-AL-PANEL.md"
    if not pedidos.exists():
        pedidos.write_text(estandar.PEDIDOS_EJEMPLO, encoding="utf-8")
        hechos.append(pedidos.name)
    return hechos


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--instalar", metavar="ARCHIVO", help="ruta, o - para la entrada")
    p.add_argument("--sin-erp", action="store_true", help="no tocar el ERP")
    p.add_argument(
        "--estandar", metavar="CARPETA", help="escribir el estándar y las plantillas"
    )
    args = p.parse_args()
    carpeta = get_settings().marketing_dir

    if args.estandar:
        for hecho in generar_estandar(Path(args.estandar)):
            print(f"  ✔ {hecho}")
        return 0

    if not args.instalar:
        actual = instalada(carpeta)
        print(f"  En el panel: {describir(actual)}" if actual else "  En el panel: nada")
        return 0

    datos = (
        sys.stdin.buffer.read()
        if args.instalar == "-"
        else Path(args.instalar).read_bytes()
    )
    try:
        nuevo, archivos, informe = instalar(datos, carpeta)
    except ValueError as exc:
        print(f"  ✘ NO se subió: {exc}")
        return 1
    print(f"  ✔ Marketing en el panel: {describir(nuevo, archivos)}")
    if nuevo.formato_mas_nuevo:
        print(
            "  ⚠ El formato es más nuevo de lo que sabe mostrar el panel: lo nuevo "
            "no se ve hasta que el Claude de VentaBot lo agregue."
        )
    if informe.avisos:
        print(f"  ⚠ {len(informe.avisos)} aviso(s) del estándar (subió igual):")
        for aviso in informe.avisos[:12]:
            print(f"      · {aviso}")
        if len(informe.avisos) > 12:
            print("      · … el resto, en el panel → Biblioteca → Calidad de los datos")
    if informe.pedidos_pendientes:
        print(
            f"  📝 {len(informe.pedidos_pendientes)} pedido(s) al panel pendientes "
            "(PEDIDOS-AL-PANEL.md): díselos al Claude de VentaBot."
        )
    if not args.sin_erp:
        print(f"  ERP: {actualizar_erp(carpeta)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
