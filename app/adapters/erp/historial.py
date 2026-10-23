"""La sábana de ventas real dentro del ERP (`vb erp --importar-sabana ARCHIVO`).

Reconcilia, igual que el bot (ver `sheets.py`): cada venta de la sábana tiene
su referencia («SABANA 2026-01 F14», en `Pedido_Ref`), así que importar dos
veces no duplica nada: se actualiza lo que cambió, se agrega lo nuevo y se
borra la fila de una venta que ya no está en la sábana. Las filas del bot
(«PED-…») no se tocan, salvo las de prueba si se pide `quitar_del_bot`.

- **Ventas**: una fila por venta (un anillo de 3 huellitas es UNA fila, con
  sus tres colores). Estado «Entregado»: es historia.
- **Pagos**: el saldo (total − abono) como pago contra entrega 10 días después
  de la venta, sin pasar del último día con ventas. La sábana no dice cuándo
  se cobró; sin esta fila el ERP mostraría $60 M «por cobrar» que ya entraron.
  Queda anotado como supuesto en la `Nota`.
- Las filas de prueba del bot salen con `quitar_del_bot` (sus referencias),
  junto con sus pagos y lotes de producción.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from app.adapters.erp.sheets import Hoja, _celda, _letra, _Tabla, _valor
from app.domain import erp
from app.domain.sabana import PREFIJO, Sabana, VentaDeSabana

#: Días entre la venta y el cobro del saldo (supuesto: producción + envío).
DIAS_HASTA_EL_SALDO = 10
MEDIO_DEL_SALDO = "Otro"
NOTA_DEL_SALDO = "saldo contra entrega (supuesto: la sábana no dice cuándo se cobró)"


@dataclass
class ResultadoImportacion:
    nuevas: int = 0
    actualizadas: int = 0
    quitadas: int = 0
    pagos_nuevos: int = 0
    pagos_actualizados: int = 0
    pagos_quitados: int = 0
    del_bot_quitadas: int = 0
    avisos: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"ventas +{self.nuevas} ~{self.actualizadas} −{self.quitadas} · "
            f"pagos +{self.pagos_nuevos} ~{self.pagos_actualizados} "
            f"−{self.pagos_quitados}"
            + (
                f" · prueba del bot −{self.del_bot_quitadas}"
                if self.del_bot_quitadas
                else ""
            )
        )


def fila_de_venta(v: VentaDeSabana, venta_id: str) -> dict:
    return {
        "Venta_ID": venta_id,
        "Fecha": v.fecha.isoformat(),
        "Producto": v.producto,
        "Celular_Cliente": v.celular,
        "Canal": v.canal,
        "Ciudad": "",
        "Talla": v.talla,
        "Color_Detalle": " | ".join(v.colores),
        "Grabado": "♡".join(v.grabados),
        "Cantidad": 1,
        "Precio_Unit": v.total,
        "Abono_Inicial": v.abono,
        "Medio_Pago": "",
        "Estado": "Entregado",
        erp.REFERENCIA: v.ref,
    }


def _comparable(x) -> str:
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    return str(x).strip().lstrip("'")


def _escribir_fila(tabla: _Tabla, hoja: str, n: int, valores: dict[int, object]):
    """Una fila en tramos de columnas seguidas (menos rangos que celda a celda)."""
    salida = []
    cols = sorted(valores)
    inicio = previo = cols[0]
    tramo = [valores[inicio]]
    for c in cols[1:]:
        if c == previo + 1:
            tramo.append(valores[c])
        else:
            salida.append((f"{hoja}!{_letra(inicio)}{n}", [tramo]))
            inicio, tramo = c, [valores[c]]
        previo = c
    salida.append((f"{hoja}!{_letra(inicio)}{n}", [tramo]))
    return salida


def _dia(x) -> str:
    """La fecha de una celda como AAAA-MM-DD («19/09/2026» o «2026-09-19»)."""
    t = str(x or "").strip()
    if len(t) >= 10 and t[2] == "/" and t[5] == "/":
        return f"{t[6:10]}-{t[3:5]}-{t[0:2]}"
    return t[:10]


def importar(
    hoja: Hoja,
    sabana: Sabana,
    *,
    quitar_del_bot: frozenset[str] = frozenset(),
    reales_desde: str = "",
) -> ResultadoImportacion:
    """Deja Ventas y Pagos con la sábana.

    Salen del ERP las pruebas del bot: los códigos de `quitar_del_bot` y, si hay
    día real, toda fila «PED-…» con fecha anterior (pedidos de prueba que ya ni
    están en la base del bot: pasó el 01/10 con 8 de septiembre).
    """
    v_filas, p_filas, pr_filas = hoja.leer(
        ["Ventas!A3:AH", "Pagos!A3:H", "Produccion!A3:L"]
    )
    ventas = _Tabla("Ventas", v_filas, "Fecha")
    pagos = _Tabla("Pagos", p_filas, "Fecha")
    produccion = _Tabla("Produccion", pr_filas, "Fecha")
    r = ResultadoImportacion()
    faltan = [c for c in (*erp.COLUMNAS_VENTA, erp.REFERENCIA) if ventas.col(c) is None]
    if faltan:
        r.avisos.append(f"Ventas no tiene las columnas {faltan}: no se importa")
        return r
    escrituras: list[tuple[str, list[list]]] = []
    c_ref, c_id = ventas.col(erp.REFERENCIA), ventas.col("Venta_ID")
    columnas = {c: ventas.col(c) for c in (*erp.COLUMNAS_VENTA, erp.REFERENCIA)}

    def vaciar(tabla: _Tabla, nombre: str, i: int, cols: list[int]) -> None:
        escrituras.extend(
            _escribir_fila(tabla, nombre, tabla.numero(i), dict.fromkeys(cols, ""))
        )
        # Queda libre: lo nuevo se escribe ahí, sin huecos arriba.
        tabla.filas[i] = []

    # Lo que hay: filas de la sábana por referencia, y las de prueba del bot.
    fila_de_ref: dict[str, int] = {}
    ids: list[str] = []
    ids_quitados: set[str] = set()
    refs_quitadas: set[str] = set()
    c_fecha = ventas.col("Fecha")
    for i, f in enumerate(ventas.filas):
        ref = str(_valor(f, c_ref)).strip()
        vid = str(_valor(f, c_id)).strip()
        vieja = (
            bool(reales_desde)
            and ref.startswith("PED-")
            and _dia(_valor(f, c_fecha)) < reales_desde
        )
        if ref in quitar_del_bot or vieja:
            vaciar(ventas, "Ventas", i, list(columnas.values()))
            ids_quitados.add(vid)
            refs_quitadas.add(ref)
            r.del_bot_quitadas += 1
            continue
        if vid:
            ids.append(vid)
        if ref.startswith(PREFIJO):
            fila_de_ref[ref] = i
    if ids_quitados:
        # La numeración sigue sin los de prueba (V0001 es la primera venta real).
        ids = [x for x in ids if x not in ids_quitados]

    vigentes = {v.ref for v in sabana.ventas}
    for ref, i in fila_de_ref.items():
        if ref not in vigentes:
            ids.remove(str(_valor(ventas.filas[i], c_id)).strip())
            vaciar(ventas, "Ventas", i, list(columnas.values()))
            r.quitadas += 1

    id_de_ref: dict[str, str] = {}
    for v in sabana.ventas:
        if v.ref in fila_de_ref:
            i = fila_de_ref[v.ref]
            venta_id = str(_valor(ventas.filas[i], c_id)).strip()
            deseada = fila_de_venta(v, venta_id)
            cambios = {
                columnas[k]: _celda(x)
                for k, x in deseada.items()
                if _comparable(_valor(ventas.filas[i], columnas[k])) != _comparable(x)
            }
            if cambios:
                escrituras.extend(
                    _escribir_fila(ventas, "Ventas", ventas.numero(i), cambios)
                )
                r.actualizadas += 1
        else:
            venta_id = erp.siguiente_venta_id(ids)
            ids.append(venta_id)
            fila = fila_de_venta(v, venta_id)
            n = ventas.siguiente_libre()
            escrituras.extend(
                _escribir_fila(
                    ventas, "Ventas", n, {columnas[k]: _celda(x) for k, x in fila.items()}
                )
            )
            r.nuevas += 1
        id_de_ref[v.ref] = venta_id

    # Pagos: el saldo de cada venta de la sábana; fuera los de prueba del bot.
    cp = {c: pagos.col(c) for c in erp.COLUMNAS_PAGO}
    if None in cp.values():
        r.avisos.append("Pagos no tiene las columnas de siempre: no se escriben saldos")
    else:
        ultimo = max((v.fecha for v in sabana.ventas), default=None)
        pago_de_ref: dict[str, int] = {}
        for i, f in enumerate(pagos.filas):
            nota = str(_valor(f, cp["Nota"])).strip()
            vid = str(_valor(f, cp["Venta_ID"])).strip()
            if vid in ids_quitados or any(c in nota for c in refs_quitadas):
                vaciar(pagos, "Pagos", i, list(cp.values()))
                continue
            if nota.startswith(PREFIJO):
                pago_de_ref[nota.split(" · ")[0]] = i
        for ref, i in pago_de_ref.items():
            v = next((x for x in sabana.ventas if x.ref == ref), None)
            if v is None or not v.saldo:
                vaciar(pagos, "Pagos", i, list(cp.values()))
                r.pagos_quitados += 1
        for v in sabana.ventas:
            if not v.saldo:
                continue
            fecha = v.fecha + timedelta(days=DIAS_HASTA_EL_SALDO)
            if ultimo and fecha > ultimo:
                fecha = max(ultimo, v.fecha)
            fila = {
                "Fecha": fecha.isoformat(),
                "Venta_ID": id_de_ref[v.ref],
                "Monto": v.saldo,
                "Medio_Pago": MEDIO_DEL_SALDO,
                "Nota": f"{v.ref} · {NOTA_DEL_SALDO}",
            }
            if v.ref in pago_de_ref:
                i = pago_de_ref[v.ref]
                cambios = {
                    cp[k]: x
                    for k, x in fila.items()
                    if _comparable(_valor(pagos.filas[i], cp[k])) != _comparable(x)
                }
                if cambios:
                    escrituras.extend(
                        _escribir_fila(pagos, "Pagos", pagos.numero(i), cambios)
                    )
                    r.pagos_actualizados += 1
            else:
                n = pagos.siguiente_libre()
                escrituras.extend(
                    _escribir_fila(pagos, "Pagos", n, {cp[k]: x for k, x in fila.items()})
                )
                r.pagos_nuevos += 1

    # Producción: los lotes de prueba del bot (su Lote es el código del pedido).
    c_lote = produccion.col("Lote")
    if refs_quitadas and c_lote is not None:
        cols = [
            c
            for c in (produccion.col(x) for x in erp.COLUMNAS_PRODUCCION)
            if c is not None
        ]
        for i, f in enumerate(produccion.filas):
            if str(_valor(f, c_lote)).strip() in refs_quitadas:
                vaciar(produccion, "Produccion", i, cols)

    hoja.escribir(escrituras)
    return r
