"""El ERP de Camilo en Google Sheets, lleno por el bot (ver app.domain.erp).

════════════════════════════════════════════════════════════════════════════
CÓMO ESCRIBE (y por qué así)
════════════════════════════════════════════════════════════════════════════
· RECONCILIA, no «anota eventos». Cada vez lee lo que hay (tres rangos, una
  llamada) y escribe lo que falta o cambió (una llamada). Si Google falla o
  el PC estuvo apagado, la próxima vuelta lo deja bien: no hay eventos
  perdidos porque no hay eventos.
· Busca por ENCABEZADO y por CÓDIGO DE PEDIDO, nunca por letra ni por «última
  fila»: si Camilo mueve una columna o escribe una venta a mano, sigue bien.
· Escribe en la PRIMERA FILA VACÍA de cada hoja, no «al final»: las fórmulas
  del ERP vienen copiadas hasta la fila 2003, así que «añadir al final» de la
  API escribiría debajo de todo.
· Solo columnas de captura. Nunca una fórmula, un catálogo ni el tablero.
· NUNCA bloquea al bot: corre en su hilo, y un error se registra y se sigue.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.domain import erp

log = logging.getLogger("ventabot.erp")

#: Cada cuánto se reconcilia aunque nadie mueva un pedido (segundos).
CADA_S = 600
#: Fila de los encabezados en las hojas de captura del ERP.
FILA_ENCABEZADOS = 3


class Hoja(Protocol):
    """Lo mínimo de una hoja de cálculo: leer rangos y escribirlos."""

    def leer(self, rangos: list[str]) -> list[list[list]]: ...

    def escribir(self, datos: list[tuple[str, list[list]]]) -> None: ...

    def asegurar_hoja(self, nombre: str, *, primera: bool = False) -> None: ...


# ══════════════════════════════════════════════════════════════════════════
#  LA HOJA DE VERDAD: Google Sheets por su API (cuenta de servicio)
# ══════════════════════════════════════════════════════════════════════════


class SheetsDeGoogle:
    """Google Sheets API v4 con una cuenta de servicio (sin gspread)."""

    API = "https://sheets.googleapis.com/v4/spreadsheets"

    def __init__(self, spreadsheet_id: str, credenciales: Path) -> None:
        import json

        from google.oauth2 import service_account

        tipo = json.loads(Path(credenciales).read_text(encoding="utf-8"))
        if tipo.get("type") != "service_account":
            # Pasó el 19/09: se descargó la credencial «OAuth / app de escritorio»
            # (clave «installed»). Esa sirve para que una PERSONA inicie sesión y
            # su acceso caduca; el bot necesita la de una CUENTA DE SERVICIO.
            clase = next(iter(tipo), "desconocido") if tipo else "vacío"
            raise ValueError(
                f"ese JSON es una credencial «{clase}» (OAuth), no la llave de una "
                "cuenta de servicio: crea una en IAM → Cuentas de servicio → Claves"
            )
        self._id = spreadsheet_id
        self._cred = service_account.Credentials.from_service_account_file(
            str(credenciales),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        self.correo = self._cred.service_account_email

    def _token(self) -> str:
        from google.auth.transport.requests import Request

        if not self._cred.valid:
            self._cred.refresh(Request())
        return self._cred.token

    def _pedir(self, metodo: str, ruta: str, **kw) -> dict:
        import httpx

        r = httpx.request(
            metodo,
            f"{self.API}/{self._id}{ruta}",
            headers={"Authorization": f"Bearer {self._token()}"},
            timeout=30,
            **kw,
        )
        r.raise_for_status()
        return r.json() if r.content else {}

    def titulo(self) -> tuple[str, list[str]]:
        r = self._pedir(
            "GET", "", params={"fields": "properties.title,sheets.properties.title"}
        )
        hojas = [h["properties"]["title"] for h in r.get("sheets", [])]
        return r.get("properties", {}).get("title", ""), hojas

    def leer(self, rangos: list[str]) -> list[list[list]]:
        r = self._pedir(
            "GET",
            "/values:batchGet",
            params={
                "ranges": rangos,
                "valueRenderOption": "UNFORMATTED_VALUE",
                "dateTimeRenderOption": "FORMATTED_STRING",
            },
        )
        return [v.get("values", []) for v in r.get("valueRanges", [])]

    def escribir(self, datos: list[tuple[str, list[list]]]) -> None:
        if not datos:
            return
        self._pedir(
            "POST",
            "/values:batchUpdate",
            json={
                # USER_ENTERED: «2026-09-19» entra como FECHA (las fórmulas del
                # ERP la necesitan así) y «'300…» como texto.
                "valueInputOption": "USER_ENTERED",
                "data": [{"range": r, "values": v} for r, v in datos],
            },
        )

    def asegurar_hoja(self, nombre: str, *, primera: bool = False) -> None:
        """Crea la hoja si falta. Si ya existe, no la toca ni la mueve."""
        _, hojas = self.titulo()
        if nombre in hojas:
            return
        propiedades: dict = {"title": nombre}
        if primera:
            # La primera pestaña es lo que se ve al abrir el ERP.
            propiedades["index"] = 0
        self._pedir(
            "POST",
            ":batchUpdate",
            json={"requests": [{"addSheet": {"properties": propiedades}}]},
        )

    def pestanas(self) -> dict[str, dict]:
        """{título: {"id": sheetId, "graficas": [chartId…]}}: para formatear y
        para rehacer las gráficas sin duplicarlas."""
        r = self._pedir(
            "GET",
            "",
            params={"fields": "sheets(properties(title,sheetId),charts(chartId))"},
        )
        return {
            h["properties"]["title"]: {
                "id": h["properties"]["sheetId"],
                "graficas": [g["chartId"] for g in h.get("charts", [])],
            }
            for h in r.get("sheets", [])
        }

    def lote(self, pedidos: list[dict]) -> None:
        """Formato, gráficas, filas nuevas: el `batchUpdate` de la hoja entera."""
        if pedidos:
            self._pedir("POST", ":batchUpdate", json={"requests": pedidos})


class HojaEnMemoria:
    """Una hoja de mentira para las pruebas: {nombre: filas} desde la fila 1."""

    def __init__(self, hojas: dict[str, list[list]]) -> None:
        self.hojas = {k: [list(f) for f in v] for k, v in hojas.items()}
        self.escrituras: list[tuple[str, list[list]]] = []
        #: Lo que se mandó por `lote` y las gráficas que quedaron, por hoja.
        self.lotes: list[list[dict]] = []
        self.graficas: dict[str, list[int]] = {}

    def hojas_ids(self) -> dict[str, int]:
        return {nombre: i for i, nombre in enumerate(self.hojas)}

    def pestanas(self) -> dict[str, dict]:
        return {
            nombre: {"id": i, "graficas": list(self.graficas.get(nombre, []))}
            for nombre, i in self.hojas_ids().items()
        }

    def lote(self, pedidos: list[dict]) -> None:
        """Guarda lo pedido y simula lo que importa: gráficas que se crean y se
        borran (para probar que rehacerlas no las duplica)."""
        self.lotes.append(pedidos)
        por_id = {i: n for n, i in self.hojas_ids().items()}
        for p in pedidos:
            if "addChart" in p:
                hoja = p["addChart"]["chart"]["position"]["overlayPosition"][
                    "anchorCell"
                ]["sheetId"]
                lista = self.graficas.setdefault(por_id[hoja], [])
                lista.append(1000 + sum(len(x) for x in self.graficas.values()))
            if "deleteEmbeddedObject" in p:
                oid = p["deleteEmbeddedObject"]["objectId"]
                for lista in self.graficas.values():
                    if oid in lista:
                        lista.remove(oid)

    def leer(self, rangos: list[str]) -> list[list[list]]:
        salida = []
        for rango in rangos:
            nombre, celdas = rango.split("!")
            nombre = nombre.strip("'")
            desde = int("".join(c for c in celdas.split(":")[0] if c.isdigit()))
            salida.append([list(f) for f in self.hojas[nombre][desde - 1 :]])
        return salida

    def asegurar_hoja(self, nombre: str, *, primera: bool = False) -> None:
        if nombre not in self.hojas:
            self.hojas[nombre] = []
            if primera:
                self.hojas = {nombre: self.hojas.pop(nombre), **self.hojas}

    def escribir(self, datos: list[tuple[str, list[list]]]) -> None:
        for rango, valores in datos:
            self.escrituras.append((rango, valores))
            nombre, celda = rango.split("!")
            # «'CENTRO DE MANDO'!A1»: con espacios, Sheets pide comillas.
            nombre = nombre.strip("'")
            col = _indice_de_columna("".join(c for c in celda if c.isalpha()))
            fila = int("".join(c for c in celda if c.isdigit()))
            hoja = self.hojas[nombre]
            # Un bloque de varias filas, como hace la API de verdad.
            for desplazamiento, fila_de_valores in enumerate(valores):
                while len(hoja) < fila + desplazamiento:
                    hoja.append([])
                renglon = hoja[fila + desplazamiento - 1]
                while len(renglon) < col + len(fila_de_valores):
                    renglon.append("")
                for i, v in enumerate(fila_de_valores):
                    renglon[col + i] = v


# ══════════════════════════════════════════════════════════════════════════
#  EL RECONCILIADOR
# ══════════════════════════════════════════════════════════════════════════


def _letra(indice: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA, 31 -> AF."""
    letras = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _indice_de_columna(letras: str) -> int:
    n = 0
    for c in letras:
        n = n * 26 + (ord(c.upper()) - 64)
    return n - 1


def _celda(valor):
    """Lo que se manda a la hoja. El celular va como TEXTO (con ') para que
    las fórmulas que cuentan compras por celular lo encuentren igual que a los
    que Lía escribió a mano."""
    if isinstance(valor, str) and valor.isdigit() and len(valor) >= 7:
        return "'" + valor
    return valor


def _valor(fila: list, i: int | None):
    if i is None or i >= len(fila):
        return ""
    return fila[i]


@dataclass
class Resultado:
    ventas_nuevas: int = 0
    ventas_actualizadas: int = 0
    pagos_nuevos: int = 0
    produccion_nueva: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def algo(self) -> bool:
        return bool(
            self.ventas_nuevas
            or self.ventas_actualizadas
            or self.pagos_nuevos
            or self.produccion_nueva
        )

    def __str__(self) -> str:
        return (
            f"ventas +{self.ventas_nuevas} ~{self.ventas_actualizadas} · "
            f"pagos +{self.pagos_nuevos} · producción +{self.produccion_nueva}"
        )


class _Tabla:
    """Una hoja de captura leída: encabezados, filas y la primera vacía."""

    def __init__(self, nombre: str, filas: list[list], clave: str) -> None:
        self.nombre = nombre
        self.encabezados = [str(x).strip() for x in (filas[0] if filas else [])]
        self.filas = filas[1:]
        self._clave = clave
        self._libres: list[int] = []

    def col(self, nombre: str) -> int | None:
        return self.encabezados.index(nombre) if nombre in self.encabezados else None

    def numero(self, i: int) -> int:
        """Número de fila en la hoja de la fila i (0 = la de debajo de encabezados)."""
        return FILA_ENCABEZADOS + 1 + i

    def siguiente_libre(self) -> int:
        """Número de fila de la primera fila vacía (según la columna clave)."""
        c = self.col(self._clave)
        usadas = set(self._libres)
        for i, fila in enumerate(self.filas):
            n = self.numero(i)
            if n in usadas:
                continue
            if _valor(fila, c) in ("", None):
                self._libres.append(n)
                return n
        # Debajo de la tabla: la primera que nadie tomó (antes saltaba una fila
        # si ya se había usado una libre de adentro).
        n = self.numero(len(self.filas))
        while n in usadas:
            n += 1
        self._libres.append(n)
        return n


class ReconciliadorDelErp:
    """Deja el ERP igual a lo que dicen los pedidos. Se puede correr mil veces."""

    RANGOS = ("Ventas!A3:AH", "Pagos!A3:H", "Produccion!A3:L")

    def __init__(self, hoja: Hoja) -> None:
        self._hoja = hoja

    def reconciliar(
        self,
        pedidos: list,
        cuando: dict[str, dict[str, datetime]],
    ) -> Resultado:
        ventas, pagos, produccion = self._leer()
        r = Resultado()
        escrituras: list[tuple[str, list[list]]] = []

        # La columna del código de pedido: si no existe, se crea al final.
        c_ref = ventas.col(erp.REFERENCIA)
        if c_ref is None:
            c_ref = len(ventas.encabezados)
            while c_ref < len(ventas.encabezados) and ventas.encabezados[c_ref]:
                c_ref += 1
            escrituras.append(
                (f"Ventas!{_letra(c_ref)}{FILA_ENCABEZADOS}", [[erp.REFERENCIA]])
            )
            ventas.encabezados += [""] * (c_ref + 1 - len(ventas.encabezados))
            ventas.encabezados[c_ref] = erp.REFERENCIA
            r.avisos.append(f"se agregó la columna {erp.REFERENCIA} en Ventas")

        faltan = [x for x in erp.COLUMNAS_VENTA if ventas.col(x) is None]
        if faltan:
            r.avisos.append(f"Ventas no tiene las columnas {faltan}: no se escribe")
            return r

        fila_de_ref: dict[str, int] = {}
        id_de_ref: dict[str, str] = {}
        ids = []
        for i, fila in enumerate(ventas.filas):
            ids.append(str(_valor(fila, ventas.col("Venta_ID"))))
            ref = str(_valor(fila, c_ref))
            if ref:
                fila_de_ref[ref] = i
                id_de_ref[ref] = ids[-1]

        c_nota_pago = pagos.col("Nota")
        pagos_de = {
            str(_valor(f, c_nota_pago)) for f in pagos.filas if _valor(f, c_nota_pago)
        }
        c_lote = produccion.col("Lote")
        lotes = {str(_valor(f, c_lote)) for f in produccion.filas}

        # Un pedido de varios anillos es una venta por anillo (`erp.por_anillo`).
        for p in (a for pedido in pedidos for a in erp.por_anillo(pedido)):
            if not erp.es_venta(p):
                continue
            fechas = cuando.get(p.id, {})
            fecha_venta = fechas.get("ANTICIPO_PAGADO") or p.updated_at or p.created_at
            if p.codigo in fila_de_ref:
                i = fila_de_ref[p.codigo]
                estado = erp.ESTADO_ERP.get(erp.S(p.estado), "Pedido")
                c_estado = ventas.col("Estado")
                if _valor(ventas.filas[i], c_estado) != estado:
                    escrituras.append(
                        (
                            f"Ventas!{_letra(c_estado)}{ventas.numero(i)}",
                            [[estado]],
                        )
                    )
                    r.ventas_actualizadas += 1
                venta_id = id_de_ref[p.codigo]
            else:
                venta_id = erp.siguiente_venta_id(ids)
                ids.append(venta_id)
                fila = erp.fila_de_venta(p, venta_id=venta_id, fecha=fecha_venta)
                n = ventas.siguiente_libre()
                for columna, valor in fila.items():
                    c = c_ref if columna == erp.REFERENCIA else ventas.col(columna)
                    escrituras.append((f"Ventas!{_letra(c)}{n}", [[_celda(valor)]]))
                r.ventas_nuevas += 1

            if erp.necesita_pago(p) and not any(p.codigo in x for x in pagos_de):
                fecha = fechas.get("SALDO_PAGADO") or p.updated_at
                fila = erp.fila_de_pago(p, venta_id=venta_id, fecha=fecha)
                n = pagos.siguiente_libre()
                for columna, valor in fila.items():
                    if (c := pagos.col(columna)) is not None:
                        escrituras.append((f"Pagos!{_letra(c)}{n}", [[valor]]))
                pagos_de.add(fila["Nota"])
                r.pagos_nuevos += 1

            if erp.necesita_produccion(p) and p.codigo not in lotes:
                fecha = fechas.get("PRODUCCION_LISTA") or p.updated_at
                fila = erp.fila_de_produccion(p, fecha=fecha)
                n = produccion.siguiente_libre()
                for columna, valor in fila.items():
                    if (c := produccion.col(columna)) is not None:
                        escrituras.append((f"Produccion!{_letra(c)}{n}", [[valor]]))
                lotes.add(p.codigo)
                r.produccion_nueva += 1

        self._hoja.escribir(escrituras)
        return r

    def _leer(self):
        v, p, pr = self._hoja.leer(list(self.RANGOS))
        return (
            _Tabla("Ventas", v, "Fecha"),
            _Tabla("Pagos", p, "Fecha"),
            _Tabla("Produccion", pr, "Fecha"),
        )


# ══════════════════════════════════════════════════════════════════════════
#  EL QUE LO CORRE: en su hilo, cada 10 minutos y cuando se mueve un pedido
# ══════════════════════════════════════════════════════════════════════════


class ErpEnSheets:
    """Lo que el contenedor conoce del ERP: `pedido_movido` y nada más."""

    def __init__(
        self,
        hoja: Hoja,
        pedidos: Callable[[], list],
        cuando: Callable[[], dict],
        cada_s: float = CADA_S,
        accesos: Callable[[], list[list]] | None = None,
        hoja_de_accesos: str = "CENTRO DE MANDO",
        foto: Callable[[Hoja], object] | None = None,
        foto_cada_s: float = 3600,
    ) -> None:
        self._hoja = hoja
        #: Las filas de la hoja CENTRO DE MANDO: dónde está el bot y cómo abrir
        #: cada cosa. Se reescribe en cada vuelta, así que en un servidor la
        #: dirección correcta siempre está en el mismo sitio (Camilo, 20/09).
        self._accesos = accesos
        self._hoja_de_accesos = hoja_de_accesos
        self._reconciliador = ReconciliadorDelErp(hoja)
        self._pedidos, self._cuando = pedidos, cuando
        self._cada = cada_s
        #: La foto de finanzas para el panel (01/10): cada hora, después de las
        #: ventas y aparte (si falla, no cuesta la sincronización).
        self._foto, self._foto_cada = foto, foto_cada_s
        self._ultima_foto = 0.0
        self._despertar = threading.Event()
        self._candado = threading.Lock()
        self.ultimo: Resultado | None = None
        self._hilo = threading.Thread(target=self._trabajar, name="erp", daemon=True)
        self._hilo.start()

    def pedido_movido(self, pedido=None, estado: str = "") -> None:
        """Un pedido se movió: que el ERP se ponga al día ya (sin esperar)."""
        self._despertar.set()

    def sincronizar(self) -> Resultado:
        with self._candado:
            r = self._reconciliador.reconciliar(self._pedidos(), self._cuando())
            self.ultimo = r
            if r.algo or r.avisos:
                log.info("ERP: %s %s", r, " · ".join(r.avisos))
            return r

    def publicar_accesos(self) -> None:
        """Escribe la hoja CENTRO DE MANDO. Nunca falla hacia arriba.

        Un problema aquí —una hoja protegida, un permiso— no puede costar la
        sincronización de las ventas, que es lo que de verdad importa del ERP.
        """
        if self._accesos is None:
            return
        nombre = self._hoja_de_accesos
        try:
            filas = self._accesos()
            self._hoja.asegurar_hoja(nombre, primera=True)
            self._hoja.escribir([(f"'{nombre}'!A1", filas)])
        except Exception as exc:
            log.warning("no se pudo escribir la hoja %s (%s)", nombre, exc)

    def tomar_foto(self, ahora: float | None = None) -> bool:
        """La foto de finanzas si ya pasó una hora. Nunca falla hacia arriba."""
        import time

        ahora = time.monotonic() if ahora is None else ahora
        if self._foto is None or (
            self._ultima_foto and ahora - self._ultima_foto < self._foto_cada
        ):
            return False
        self._ultima_foto = ahora
        try:
            self._foto(self._hoja)
            return True
        except Exception as exc:
            log.warning("no se pudo tomar la foto de finanzas (%s)", exc)
            return False

    def _trabajar(self) -> None:  # pragma: no cover - hilo de fondo
        while True:
            try:
                self.sincronizar()
            except Exception as exc:
                log.warning("no se pudo poner al día el ERP (%s)", exc)
            # Aparte y después: las ventas primero, siempre.
            self.publicar_accesos()
            self.tomar_foto()
            self._despertar.wait(self._cada)
            self._despertar.clear()
