"""El ERP (HUELLAS_ERP_v1 en Google Sheets): revisarlo, llenarlo, vaciarlo.

    vb erp                  ¿está conectado? ¿la estructura es la que espera el bot?
    vb erp --sincronizar    ponerlo al día YA (el bot lo hace solo cada 10 min)
    vb erp --vaciar         respaldo + borrar los DATOS de captura, dejando
                            fórmulas, catálogos y tablero (para empezar limpio)
    vb erp --importar-sabana ARCHIVO.xlsx   la sábana real de ventas → Ventas y Pagos
                            (no duplica; quita las pruebas del bot) y monta el ERP
    vb erp --montar         catálogos, Costeo, gastos supuestos, Gráficas y LEEME
    vb erp --cuestionario ARCHIVO.xlsx   el Excel para Lía: lo que el ERP todavía
                            supone (preguntas) y las hojas del mes que el bot no
                            llena (compras, gastos, plata, equipos, ventas fuera
                            del bot, inventario)
    vb erp --importar-lia ARCHIVO.xlsx   lo que Lía llenó → ERP (no duplica) y lo
                            recalcula

El bot escribe solo en las hojas de captura (Ventas, Pagos, Produccion) y solo
en sus columnas amarillas: todo lo demás del ERP se calcula con sus fórmulas.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.infra.consola import preparar_salida

# UTF-8 pase lo que pase: sin esto, redirigir la salida a un archivo (o
# leerla desde otro proceso) revienta en Windows al imprimir un ✔.
preparar_salida()


from app.infra.settings import get_settings

V, R, A, B, C, RST = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[1m",
    "\033[36m",
    "\033[0m",
)
OK, MAL = f"{V}✔{RST}", f"{R}✘{RST}"

#: Las hojas donde se ESCRIBE (captura). Solo estas se vacían.
CAPTURA = ("Ventas", "Pagos", "Compras", "Produccion", "Gastos", "Publicidad", "Ajustes")
#: Donde van los respaldos del ERP antes de vaciarlo (fuera del repo).
RESPALDOS = Path.home() / "Documents" / "Respaldos" / "ERP"


def _pasos_para_conectar(s) -> None:
    ruta = s.google_service_account_json or (
        Path.home() / "Documents" / "Luna Joyas" / "credenciales" / "erp-google.json"
    )
    print(f"""
  {B}Falta conectar el ERP (una sola vez, ~10 minutos):{RST}

  1. Entra a https://console.cloud.google.com con tu cuenta de Google y, arriba,
     escoge el proyecto que ya tienes (o {B}Proyecto nuevo{RST} → «VentaBot»).
  2. Menú ☰ → {B}APIs y servicios → Biblioteca{RST} → busca «Google Sheets API»
     → {B}Habilitar{RST}.
  3. Menú ☰ → {B}IAM y administración → Cuentas de servicio → Crear cuenta de
     servicio{RST} → nombre «ventabot-erp» → Crear y continuar → Listo (sin roles).
  4. Entra a la cuenta recién creada → pestaña {B}Claves → Agregar clave →
     Crear clave nueva → JSON{RST}. Se descarga un archivo .json.
  5. Mueve ese archivo a:
        {ruta}
     (es una llave: NO la subas a ningún lado ni la mandes por chat).
  6. Copia el {B}correo{RST} de la cuenta de servicio (termina en
     «.iam.gserviceaccount.com») y en tu ERP de Google Sheets:
     {B}Compartir{RST} → pega ese correo → rol {B}Editor{RST} → Enviar.
  7. En el .env deja:
        GOOGLE_SERVICE_ACCOUNT_JSON={ruta}
        SHEETS_SPREADSHEET_ID=<lo que va entre /d/ y /edit en el enlace del ERP>
  8. Corre otra vez  {B}vb erp{RST}  (y luego reinicia el bot).
""")


def _abrir(s):
    from app.adapters.erp.sheets import SheetsDeGoogle

    if not s.sheets_spreadsheet_id:
        print(f"  {MAL} falta SHEETS_SPREADSHEET_ID en el .env")
        return None
    ruta = s.google_service_account_json
    if not ruta or not Path(ruta).is_file():
        print(f"  {MAL} no está el archivo de la cuenta de servicio de Google")
        _pasos_para_conectar(s)
        return None
    try:
        hoja = SheetsDeGoogle(s.sheets_spreadsheet_id, Path(ruta))
    except ValueError as exc:
        print(f"  {MAL} {exc}")
        _pasos_para_conectar(s)
        return None
    print(f"  {OK} cuenta de servicio: {hoja.correo}")
    try:
        titulo, hojas = hoja.titulo()
    except Exception as exc:
        print(f"  {MAL} Google no deja abrir el ERP ({exc})")
        print(
            f"      {A}→{RST} compártelo como {B}Editor{RST} con {hoja.correo} "
            "y revisa el SHEETS_SPREADSHEET_ID"
        )
        return None
    print(f"  {OK} ERP abierto: «{titulo}» ({len(hojas)} hojas)")
    faltan = [h for h in ("Ventas", "Pagos", "Produccion") if h not in hojas]
    if faltan:
        print(f"  {MAL} le faltan las hojas {faltan}: ¿es el ERP correcto?")
        return None
    return hoja


def revisar(s) -> int:
    from app.adapters.erp.sheets import ReconciliadorDelErp
    from app.domain import erp

    hoja = _abrir(s)
    if hoja is None:
        return 1
    ventas, pagos, produccion = ReconciliadorDelErp(hoja)._leer()
    faltan = [c for c in erp.COLUMNAS_VENTA if ventas.col(c) is None]
    faltan += [
        f"Pagos.{c}"
        for c in ("Fecha", "Venta_ID", "Monto", "Nota")
        if pagos.col(c) is None
    ]
    faltan += [
        f"Produccion.{c}"
        for c in ("Fecha", "Lote", "Producto", "Cantidad")
        if produccion.col(c) is None
    ]
    if faltan:
        print(f"  {MAL} columnas que el bot necesita y no están: {faltan}")
        return 1
    print(f"  {OK} estructura: Ventas, Pagos y Produccion con sus columnas")
    n = sum(1 for f in ventas.filas if f and len(f) > 1 and f[1] not in ("", None))
    print(f"  {OK} ventas registradas hoy en el ERP: {n}")
    print(f"\n  {V}{B}Listo.{RST} El bot lo llena solo (cada 10 min y al mover")
    print("  un pedido).\n")
    return 0


def sincronizar(s) -> int:
    from app.adapters.erp.sheets import ReconciliadorDelErp
    from app.adapters.repositories.sqlite_store import SqliteDB
    from app.adapters.repositories.ventas import BaseDeVentas
    from app.domain import erp

    hoja = _abrir(s)
    if hoja is None:
        return 1
    base = BaseDeVentas(SqliteDB(s.sqlite_path))
    pedidos = erp.solo_reales(base.pedidos(), s.ventas_reales_desde)
    r = ReconciliadorDelErp(hoja).reconciliar(pedidos, base.cuando())
    print(f"  {OK} {r}")
    for aviso in r.avisos:
        print(f"  {A}·{RST} {aviso}")
    return 0


def vaciar(s, *, confirmado: bool) -> int:
    """Deja las hojas de captura sin datos. Las FÓRMULAS se quedan: se leen con
    sus fórmulas y se vuelve a escribir cada fila con las fórmulas y en blanco
    lo que era un dato. Antes, un respaldo completo en JSON."""
    hoja = _abrir(s)
    if hoja is None:
        return 1
    rangos = [f"{h}!A4:AH3000" for h in CAPTURA]
    filas_por_hoja = hoja._pedir(
        "GET",
        "/values:batchGet",
        params={"ranges": rangos, "valueRenderOption": "FORMULA"},
    ).get("valueRanges", [])
    datos, respaldo, total = [], {}, 0
    for nombre, rango in zip(CAPTURA, filas_por_hoja, strict=False):
        filas = rango.get("values", [])
        respaldo[nombre] = filas
        for i, fila in enumerate(filas):
            if not any(v not in ("", None) and not str(v).startswith("=") for v in fila):
                continue
            limpia = [v if str(v).startswith("=") else "" for v in fila]
            datos.append((f"{nombre}!A{4 + i}", [limpia]))
            total += 1
    print(f"  {A}·{RST} filas con datos en las hojas de captura: {total}")
    if not total:
        print(f"  {OK} ya estaba vacío")
        return 0
    RESPALDOS.mkdir(parents=True, exist_ok=True)
    hora = datetime.now(timezone(timedelta(hours=-5)))  # Colombia
    archivo = RESPALDOS / f"erp-antes-de-vaciar-{hora:%Y%m%d-%H%M}.json"
    archivo.write_text(json.dumps(respaldo, ensure_ascii=False, default=str), "utf-8")
    print(f"  {OK} respaldo completo: {archivo}")
    if not confirmado:
        print(f"\n  Para vaciar de verdad:  {B}vb erp --vaciar --si{RST}\n")
        return 0
    hoja.escribir(datos)
    print(f"  {OK} vaciado: {total} filas (fórmulas, catálogos y tablero intactos)")
    return 0


def _pesos(n: float) -> str:
    return "$" + f"{n:,.0f}".replace(",", ".")


def _resumen_de_la_sabana(sab, hoy: str) -> str:
    """El texto del LEEME: qué se importó y qué no cuadra con el resumen a mano."""
    total = sum(v.total for v in sab.ventas)
    meses = sorted({v.mes for v in sab.ventas})
    distinto = [
        f"{m % 100:02d}/{m // 100}: {a} ventas y {_pesos(c)} en el detalle contra {b} y "
        f"{_pesos(d)} en el resumen"
        for m, a, b, c, d in sab.cuadre()
        if (a, c) != (b, d)
    ]
    return (
        f"El {hoy} se importó la sábana «HUELLAS» de Camilo: {len(sab.ventas)} "
        f"ventas de {meses[0] % 100:02d}/{meses[0] // 100} a "
        f"{meses[-1] % 100:02d}/{meses[-1] // 100} por {_pesos(total)} (una fila por "
        "venta: un anillo de 3 huellitas es UNA fila con sus 3 colores; las referencias "
        "SABANA… están en Pedido_Ref). Los saldos se asumieron cobrados contra entrega "
        "10 días después (Pagos). Lo que no cuadra con el resumen que "
        "Camilo lleva a mano: " + ("; ".join(distinto) if distinto else "nada") + ". Las "
        "ventas del bot (PED-…) se suman solas desde VENTAS_REALES_DESDE. Reimportar: "
        "vb erp --importar-sabana (no duplica)."
    )


def respaldar(s, hoja, motivo: str) -> Path:
    """Todo el ERP (fórmulas y valores, cada hoja) a un JSON en `estado/respaldos`."""

    nombres = list(hoja.pestanas())
    rangos = [f"'{n}'!A1:AZ3000" for n in nombres]
    datos = {}
    for modo in ("FORMULA", "UNFORMATTED_VALUE"):
        r = hoja._pedir(
            "GET",
            "/values:batchGet",
            params={"ranges": rangos, "valueRenderOption": modo},
        )
        datos[modo] = {
            n: v.get("values", [])
            for n, v in zip(nombres, r.get("valueRanges", []), strict=False)
        }
    carpeta = Path(s.sqlite_path).parent / "respaldos"
    carpeta.mkdir(parents=True, exist_ok=True)
    hora = datetime.now(timezone(timedelta(hours=-5)))  # Colombia
    archivo = carpeta / f"erp-{motivo}-{hora:%Y%m%d-%H%M%S}.json"
    archivo.write_text(json.dumps(datos, ensure_ascii=False, default=str), "utf-8")
    return archivo


def importar_sabana(s, archivo: str, año: int) -> int:
    """La sábana real → Ventas y Pagos; fuera las pruebas del bot; y monta el ERP."""
    import io

    import openpyxl

    from app.adapters.erp.historial import importar
    from app.adapters.repositories.sqlite_store import SqliteDB
    from app.adapters.repositories.ventas import BaseDeVentas
    from app.domain import erp, sabana

    datos = sys.stdin.buffer.read() if archivo == "-" else Path(archivo).read_bytes()
    libro = openpyxl.load_workbook(io.BytesIO(datos), data_only=True, read_only=True)
    hojas = {h.title: [list(f) for f in h.iter_rows(values_only=True)] for h in libro}
    sab = sabana.leer(hojas, año)
    if not sab.ventas:
        print(f"  {MAL} la sábana no trae ventas (¿es el archivo correcto?)")
        return 1
    print(
        f"  {OK} sábana leída: {len(sab.ventas)} ventas, "
        f"{_pesos(sum(v.total for v in sab.ventas))}"
    )
    print(f"\n  {B}Mes      Detalle        Resumen a mano   Diferencia{RST}")
    for m, a, b, c, d in sab.cuadre():
        marca = OK if (a, c) == (b, d) else f"{A}≠{RST}"
        print(
            f"  {marca} {m % 100:02d}/{m // 100}  {a:3d} {_pesos(c):>12}   {b:3d} "
            f"{_pesos(d):>12}   {_pesos(c - d):>10}"
        )
    for aviso in sab.avisos:
        print(f"  {A}·{RST} {aviso}")
    if not s.ventas_reales_desde:
        print(
            f"\n  {MAL} falta VENTAS_REALES_DESDE en el .env: sin ese día, las "
            "pruebas del bot volverían a la hoja real. Ponlo (AAAA-MM-DD) y corre "
            "otra vez."
        )
        return 1
    hoja = _abrir(s)
    if hoja is None:
        return 1
    print(f"  {OK} respaldo completo del ERP: {respaldar(s, hoja, 'antes-de-sabana')}")
    base = BaseDeVentas(SqliteDB(s.sqlite_path))
    prueba = frozenset(
        p.codigo for p in base.pedidos() if erp.de_prueba(p, s.ventas_reales_desde)
    )
    r = importar(hoja, sab, quitar_del_bot=prueba, reales_desde=s.ventas_reales_desde)
    print(f"\n  {OK} ERP: {r}")
    for aviso in r.avisos:
        print(f"  {A}·{RST} {aviso}")
    hoy = datetime.now(timezone(timedelta(hours=-5)))  # Colombia
    return montar(
        s,
        hoja,
        sorted({v.mes for v in sab.ventas}),
        _resumen_de_la_sabana(sab, f"{hoy:%d/%m/%Y}"),
    )


def montar(s, hoja=None, meses: list[int] | None = None, resumen: str = "") -> int:
    """Catálogos, Costeo, gastos fijos supuestos, Gráficas, LEEME y la foto."""
    from app.adapters.erp.finanzas import guardar as guardar_finanzas
    from app.adapters.erp.montaje import montar as montar_erp

    hoja = hoja or _abrir(s)
    if hoja is None:
        return 1
    if meses is None:
        (filas,) = hoja.leer(["Config!B11:B12"])
        primero, ultimo = (int(f[0]) for f in filas[:2])
        meses, m = [], primero
        while m <= ultimo:
            meses.append(m)
            m = m + 89 if m % 100 == 12 else m + 1
    hoy = datetime.now(timezone(timedelta(hours=-5)))  # Colombia
    r = montar_erp(hoja, f"{hoy:%Y-%m-%d}", meses, resumen)
    for hecho in r.hechos:
        print(f"  {OK} {hecho}")
    # La pauta desde el primer mes con ventas reales, las ciudades y la foto.
    from scripts.marketing import actualizar_erp

    print(f"  {OK} marketing: {actualizar_erp(s.marketing_dir)}")
    guardar_finanzas(hoja, s.finanzas_foto_del_erp)
    print(f"  {OK} foto de finanzas para el panel: {s.finanzas_foto_del_erp}")
    return 0


def cuestionario(s, destino: str) -> int:
    """El Excel para Lía: cuestionario + las hojas del mes (`erp.cuestionario`)."""
    from app.adapters.erp.cuestionario import crear_libro

    hoja = _abrir(s)
    if hoja is None:
        return 1
    (filas,) = hoja.leer(["Cat_Materiales!A4:A60"])
    materiales = [str(f[0]).strip() for f in filas if f and str(f[0]).strip()]
    hoy = datetime.now(timezone(timedelta(hours=-5)))  # Colombia
    salida = Path(destino)
    salida.parent.mkdir(parents=True, exist_ok=True)
    crear_libro(salida, materiales, f"{hoy:%d/%m/%Y}")
    print(f"  {OK} Excel para Lía: {salida} ({len(materiales)} materiales en la lista)")
    return 0


def importar_lia(s, archivo: str) -> int:
    """Lo que Lía llenó → Costeo, Compras, Gastos, Plata, Activos, Ventas, Ajustes."""
    from app.adapters.erp.cuestionario import leer_libro, pasar_al_erp

    datos = sys.stdin.buffer.read() if archivo == "-" else Path(archivo).read_bytes()
    libro = leer_libro(datos)
    hoja = _abrir(s)
    if hoja is None:
        return 1
    print(f"  {OK} respaldo completo del ERP: {respaldar(s, hoja, 'antes-de-lia')}")
    hoy = datetime.now(timezone(timedelta(hours=-5)))  # Colombia
    r = pasar_al_erp(hoja, libro, f"{hoy:%Y-%m-%d}")
    for hecho in r.hechos or ["nada nuevo (lo de este archivo ya estaba)"]:
        print(f"  {OK} {hecho}")
    for aviso in r.avisos:
        print(f"  {A}·{RST} {aviso}")
    return montar(s, hoja)


def main() -> int:
    ap = argparse.ArgumentParser(description="El ERP en Google Sheets")
    ap.add_argument("--sincronizar", action="store_true")
    ap.add_argument("--vaciar", action="store_true")
    ap.add_argument("--si", action="store_true", help="confirma --vaciar")
    ap.add_argument("--importar-sabana", metavar="ARCHIVO", help="xlsx, o - por stdin")
    ap.add_argument("--anio", type=int, default=2026, help="año de la sábana")
    ap.add_argument("--montar", action="store_true")
    ap.add_argument("--cuestionario", metavar="ARCHIVO", help="crea el Excel para Lía")
    ap.add_argument(
        "--importar-lia", metavar="ARCHIVO", help="xlsx de Lía, o - por stdin"
    )
    args = ap.parse_args()
    s = get_settings()
    print(f"\n{C}{'=' * 74}\n  ERP · HUELLAS_ERP_v1 (Google Sheets)\n{'=' * 74}{RST}")
    if args.importar_sabana:
        return importar_sabana(s, args.importar_sabana, args.anio)
    if args.montar:
        return montar(s)
    if args.cuestionario:
        return cuestionario(s, args.cuestionario)
    if args.importar_lia:
        return importar_lia(s, args.importar_lia)
    if args.vaciar:
        return vaciar(s, confirmado=args.si)
    if args.sincronizar:
        return sincronizar(s)
    return revisar(s)


if __name__ == "__main__":
    raise SystemExit(main())
