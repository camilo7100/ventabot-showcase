#!/usr/bin/env python3
"""La prueba de verdad: conversaciones enteras contra el bot con la IA REAL (04/10).

Camilo, 04/10: «las pruebas fueron deficientes… crea una prueba de verdad
donde garantices que todas las fases funcionan: diversos ejemplos, distintas
personas, mensajes mal escritos y bien escritos, velocidades diferentes».

Qué hace:

- Arma el bot COMO EN PRODUCCIÓN (mismo prompt, mismos modelos —GPT primero,
  Claude de respaldo—, el agrupador de ráfagas, la regla de la talla de Lía)
  pero AISLADO: base temporal, canal de consola (no sale nada por WhatsApp),
  sin Chatwoot, sin ERP, sin avisos al celular, sin LangSmith.
- Cada clienta de `scripts/verdad/escenarios.py` conversa a su ritmo, todas
  a la vez (como en la vida real; los turnos se atienden de a uno, igual que
  en el servidor). Las fotos son de `scripts/verdad/fotos.py`.
- Hace de Lía cuando el escenario lo pide: confirma tallas, verifica abonos y
  saldos, marca el anillo listo (con foto) y despacha con guía.
- Califica CADA paso: las reglas de siempre (`REGLAS`) y lo que se espera de
  esa etapa. Al final, el marcador por etapa y por regla, el costo y lo que
  tardó, y la conversación entera de quien falló.

Cómo se corre (en el servidor, ~10–20 min, centavos de dólar):

    ssh servidor-demo 'cd ~/ventabot && sudo docker compose run --rm -T \
        ventabot python scripts/prueba_de_verdad.py'

`--solo laura,cadena` corre solo esas clientas. Sale con código 1 si algo
falló: no se despliega un cambio del flujo sin que esto pase entero.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

TEMPORAL = Path(tempfile.mkdtemp(prefix="verdad-"))
#: Aislado ANTES de importar nada del bot: todo lo que escribe va a TEMPORAL.
os.environ.update(
    REPOSITORY_BACKEND="sqlite",
    SQLITE_PATH=str(TEMPORAL / "ventabot.db"),
    VENTAS_EXCEL=str(TEMPORAL / "ventas.xlsx"),
    CHANNEL_BACKEND="console",
    WA_ACCESS_TOKEN="",
    CHATWOOT_URL="",
    CHATWOOT_TOKEN="",
    SHEETS_SPREADSHEET_ID="",
    AVISOS_BACKEND="ninguno",
    NTFY_TEMA="",
    LANGSMITH_TRACING="false",
    # Las clientas esperan la apertura de siempre (la presentación de primeras);
    # la del peludito (13/10) la prueban sus tests y las charlas a mano.
    APERTURA_PELUDITO="false",
    RECORDATORIOS="false",
)

from scripts.verdad import fotos
from scripts.verdad.compradora import (
    TOPE_DE_TURNOS,
    lo_que_se_espera,
    que_pregunta,
    respuesta,
)
from scripts.verdad.escenarios import CLIENTAS, Clienta, Paso
from scripts.verdad.revisiones import REGLAS, Estado, Salida, plano

#: Entre mensaje y mensaje de una ráfaga (menos que la ventana de 5 s).
ENTRE_RAFAGA_S = 1.5
#: Lo más que se espera un turno antes de darlo por perdido.
TOPE_TURNO_S = 120
#: Cuántas clientas escriben a la vez.
A_LA_VEZ = 4


@dataclass
class Resultado:
    clienta: Clienta
    pasos: list[tuple[Paso, Salida, list[str]]] = field(default_factory=list)
    error: str = ""

    @property
    def fallas(self) -> int:
        return sum(1 for _, _, p in self.pasos if p) + (1 if self.error else 0)


class Prueba:
    def __init__(self) -> None:
        import app.infra.container as contenedor

        # Las fotos de la clienta salen de `fotos.py`: el `media_id` es su nombre.
        contenedor.FakeMedia.download = lambda self, ref: fotos.bytes_de(ref)
        self.c = contenedor.get_container()
        if self.c.agrupador is None or not self.c.agrupador.activo:
            print("  ⚠️ el agrupador de ráfagas no está activo: AGRUPAR_SEGUNDOS")
        self._n = 0

    # -- lo que manda la clienta ---------------------------------------------

    def _mensaje(self, clienta: Clienta, texto: str | None, foto: str | None, producto):
        from app.domain.catalogo_meta import con_el_producto
        from app.domain.models import Channel, InboundMessage, MediaRef, conversation_id

        self._n += 1
        media = []
        if foto:
            tipo = fotos.tipo_de(foto)
            media.append(
                MediaRef(
                    kind=tipo,  # type: ignore[arg-type]
                    media_id=foto,
                    mime_type="application/pdf" if tipo == "document" else "image/jpeg",
                    filename=f"{foto}.pdf" if tipo == "document" else None,
                )
            )
        raw: dict = {"type": "image" if foto else "text"}
        if producto:
            raw["context"] = {"referred_product": {"product_retailer_id": producto}}
        m = InboundMessage(
            channel=Channel.WHATSAPP,
            external_message_id=f"wamid.verdad.{self._n}",
            conversation_id=conversation_id(Channel.WHATSAPP, clienta.numero),
            sender_id=clienta.numero,
            sender_name=clienta.nombre,
            text=texto,
            media=media,
            raw=raw,
        )
        return con_el_producto(m, self.c.products.list_active())

    async def _esperar(self, conv: str) -> None:
        agr = self.c.agrupador
        if agr is None:
            return
        inicio = time.monotonic()
        while time.monotonic() - inicio < TOPE_TURNO_S:
            if conv not in agr._tareas and not agr._pendientes.get(conv):
                return
            await asyncio.sleep(0.3)
        raise TimeoutError(f"el turno de {conv} no terminó en {TOPE_TURNO_S} s")

    # -- lo que hace Lía -------------------------------------------------------

    def _lia(self, conv: str, accion: str) -> None:
        from app.domain.order_state import OrderState as S

        c = self.c
        if accion.startswith("confirmar_talla:"):
            c.confirmar_talla_de_conversacion(conv, float(accion.split(":")[1]))
            return
        pedido = c._pedido_de(conv)
        if pedido is None:
            raise RuntimeError(f"Lía quiso «{accion}» y no hay pedido")

        def mover(destino, **kw):
            nonlocal pedido
            c.mover_pedido(pedido, destino, actor="prueba de verdad", **kw)
            pedido = c._pedido_de(conv)

        if accion == "verificar_abono":
            # Como en el panel: «Abono recibido» y «Empezar a fabricar».
            mover(S.ANTICIPO_PAGADO)
            mover(S.EN_PRODUCCION)
        elif accion == "anillo_listo":
            mover(S.PRODUCCION_LISTA)
            c.orders.guardar_pedido(pedido.model_copy(update={"fotos": ["listo.jpg"]}))
            pedido = c._pedido_de(conv)
            mover(S.ESPERANDO_SALDO)
        elif accion == "verificar_saldo":
            mover(S.SALDO_PAGADO)
        elif accion == "despachar":
            mover(S.DESPACHADO, guia="700123456789", transportadora="Coordinadora")
        else:
            raise ValueError(f"Lía no sabe hacer «{accion}»")

    # -- lo que salió ----------------------------------------------------------

    def _ultimo(self, numero: str) -> int:
        fila = self.c.db.consultar(
            "SELECT MAX(rowid) AS n FROM outbox WHERE destinatario = ?", (numero,)
        )
        return int(fila[0]["n"] or 0)

    def _salida(self, numero: str, desde: int) -> Salida:
        s = Salida()
        for f in self.c.db.consultar(
            "SELECT payload FROM outbox WHERE destinatario = ? AND rowid > ? "
            "ORDER BY rowid",
            (numero, desde),
        ):
            p = json.loads(f["payload"] or "{}")
            texto = p.get("text") or p.get("caption") or ""
            if texto:
                s.textos.append(texto)
            if p.get("media_url"):
                s.medios.append(str(p["media_url"]).rsplit("/", 1)[-1])
            if p.get("template_name") or p.get("kind") == "template":
                s.plantillas.append(str(p.get("template_name") or "plantilla"))
        return s

    def _estado_de_la_base(self, conv: str, e: Estado) -> None:
        filas = self.c.db.consultar(
            "SELECT payload FROM conv_contexto WHERE conversation_id = ?", (conv,)
        )
        ctx = json.loads(filas[0]["payload"]) if filas else {}
        e.borrador = ctx.get("borrador") or {}
        e.pedido = None
        pid = e.borrador.get("pedido_id")
        if pid:
            p = self.c.db.consultar(
                "SELECT estado, payload FROM orders WHERE id = ?", (pid,)
            )
            if p:
                e.pedido = {
                    "estado": p[0]["estado"],
                    "payload": json.loads(p[0]["payload"]),
                }

    # -- una clienta -----------------------------------------------------------

    async def _dar_paso(self, cl: Clienta, paso: Paso, e: Estado, conv: str, r) -> Salida:
        """Manda lo de ella (o hace lo de Lía), lee lo que salió y lo califica."""
        desde = self._ultimo(cl.numero)
        inicio = time.monotonic()
        if paso.lia:
            await self.c.agrupador.en_el_hilo(lambda: self._lia(conv, paso.lia))
            if paso.lia in ("verificar_abono", "verificar_saldo"):
                e.lia_verifico_pago = True
            if paso.lia == "anillo_listo":
                e.anillo_listo = True
            if paso.lia.startswith("confirmar_talla"):
                e.mando_regla_o_medida = True
        else:
            textos = paso.rafaga or (paso.texto,)
            for i, texto in enumerate(textos):
                foto = paso.foto if i == len(textos) - 1 else None
                await self.c.recibir_mensaje(
                    self._mensaje(cl, texto, foto, paso.producto)
                )
                if paso.rafaga and i < len(textos) - 1:
                    await asyncio.sleep(ENTRE_RAFAGA_S)
            await self._esperar(conv)
        salida = self._salida(cl.numero, desde)
        salida.segundos = time.monotonic() - inicio
        # Lo que este paso cuenta de ella, antes de calificar.
        if (paso.foto or "").startswith("comprobante") or paso.dijo_que_pago:
            e.pago_reportado = True
        if paso.foto == "regla" or paso.medida:
            e.mando_regla_o_medida = True
        e.pidio_cadena = e.pidio_cadena or paso.pidio_cadena or cl.pidio_cadena
        e.pidio_cuentas = e.pidio_cuentas or paso.pidio_cuentas
        self._estado_de_la_base(conv, e)
        problemas = []
        for nombre, regla in REGLAS.items():
            if nombre == "contesta siempre" and paso.lia == "verificar_saldo":
                continue
            problemas += [f"[{nombre}] {p}" for p in regla(salida, e)]
        for esperado in paso.espera:
            problemas += esperado(salida, e)
        if any(m in salida.todo for m in ("•anillo", "•cadena", "•pedido")):
            e.resumen_visto = True
        e.anteriores += salida.textos
        r.pasos.append((paso, salida, problemas))
        marca = "✔" if not problemas else "✘"
        print(f"  {marca} {cl.clave:<14} {paso.etapa:<18} {salida.segundos:5.1f} s")
        return salida

    async def _comprar(self, cl: Clienta, e: Estado, conv: str, r, ultima: Salida):
        """Ella contesta lo que el bot pregunte, hasta pagar (o hasta que el bot
        se quede dando vueltas)."""
        c = cl.compradora
        anterior, seguidas = "", 0
        for _ in range(TOPE_DE_TURNOS):
            que = que_pregunta(ultima, e.pago_reportado)
            if que == "fin":
                break
            # No acosar (09/10): si la talla la trae ella (joyería, «te la confirmo
            # en la tarde»), el bot ya no se la pide y espera. Una clienta de
            # verdad, en ese punto, llega con la talla.
            if (
                que == "otra"
                and "?" not in ultima.todo
                and "talla" in ((e.borrador or {}).get("lo_manda_despues") or {})
                and c.talla
            ):
                que = "talla"
            if que == "esperar_a_lia" and c.talla_de_lia and not c.usadas.get("lia"):
                c.usadas["lia"] = 1
                paso = Paso("lia talla", lia=f"confirmar_talla:{c.talla_de_lia:g}")
                ultima = await self._dar_paso(cl, paso, e, conv, r)
                continue
            texto, foto = respuesta(c, que)
            if texto is None and foto is None:
                r.pasos[-1][2].append(
                    f"la compradora no supo qué contestar (pregunta «{que}»): "
                    f"«{(ultima.textos or [''])[-1][:120]}»"
                )
                return
            seguidas = seguidas + 1 if que == anterior else 0
            anterior = que
            if seguidas >= 2 and que != "pagar":
                r.pasos[-1][2].append(f"preguntó «{que}» tres veces seguidas")
                return
            etapa, espera = lo_que_se_espera(c, que, texto)
            partes = tuple(x.strip() for x in (texto or "").split("|") if x.strip())
            paso = Paso(
                etapa,
                texto=None if cl.rafagas and len(partes) > 1 else (texto or None),
                rafaga=partes if cl.rafagas and len(partes) > 1 else (),
                foto=foto,
                espera=espera,
                dijo_que_pago=que == "pagar" and bool(texto),
            )
            ultima = await self._dar_paso(cl, paso, e, conv, r)
            if c.en_el_resumen and "•" in ultima.todo and etapa != "cambio":
                faltan = [x for x in c.en_el_resumen if plano(x) not in ultima.todo]
                if faltan:
                    r.pasos[-1][2].append(f"el resumen no dice {faltan}")
        else:
            r.pasos[-1][2].append(f"no llegó al pago en {TOPE_DE_TURNOS} turnos")
            return
        # Cómo quedó el pedido.
        problemas = []
        if not e.pedido:
            problemas.append("terminó sin pedido")
        else:
            if e.pedido["estado"] != "EN_REVISION_PAGO":
                problemas.append(f"el pedido quedó en {e.pedido['estado']}")
            total = (e.pedido.get("payload") or {}).get("total_cop")
            if total != c.total:
                problemas.append(f"total {total}, se esperaba {c.total}")
        r.pasos.append((Paso("pedido final"), Salida(), problemas))
        print(f"  {'✔' if not problemas else '✘'} {cl.clave:<14} pedido final")

    async def clienta(self, cl: Clienta) -> Resultado:
        from app.domain.models import Channel, conversation_id

        r = Resultado(cl)
        e = Estado()
        conv = conversation_id(Channel.WHATSAPP, cl.numero)
        try:
            ultima = Salida()
            for paso in cl.pasos:
                ultima = await self._dar_paso(cl, paso, e, conv, r)
            if cl.compradora is not None:
                await self._comprar(cl, e, conv, r, ultima)
            for paso in cl.final:
                await self._dar_paso(cl, paso, e, conv, r)
        except Exception as exc:  # la clienta se corta, la prueba sigue
            r.error = f"{type(exc).__name__}: {exc}"
            print(f"  ✘ {cl.clave:<14} SE CORTÓ: {r.error}")
        return r

    def costo(self) -> tuple[float, int]:
        fila = self.c.db.consultar(
            "SELECT COALESCE(SUM(costo_usd), 0) AS usd, COUNT(*) AS n FROM decisiones"
        )
        return float(fila[0]["usd"]), int(fila[0]["n"])


def informe(resultados: list[Resultado], usd: float, turnos: int, minutos: float) -> str:
    por_etapa: dict[str, list[int]] = {}
    por_regla: dict[str, int] = {}
    for r in resultados:
        for paso, _, problemas in r.pasos:
            n = por_etapa.setdefault(paso.etapa, [0, 0])
            n[0 if not problemas else 1] += 1
            for p in problemas:
                if p.startswith("["):
                    regla = p[1 : p.index("]")]
                    por_regla[regla] = por_regla.get(regla, 0) + 1
    pasos = sum(len(r.pasos) for r in resultados)
    malos = sum(r.fallas for r in resultados)
    lineas = [
        "# Prueba de verdad",
        "",
        f"**{pasos - malos} de {pasos} pasos bien** · {len(resultados)} clientas · "
        f"{turnos} turnos de la IA · USD {usd:.3f} · {minutos:.1f} min",
        "",
        "## Por etapa",
        "",
        "| Etapa | Bien | Mal |",
        "|---|---|---|",
        *[f"| {e} | {b} | {m} |" for e, (b, m) in sorted(por_etapa.items())],
        "",
        "## Las reglas de siempre",
        "",
        "| Regla | Fallas |",
        "|---|---|",
        *[f"| {n} | {por_regla.get(n, 0)} |" for n in REGLAS],
        "",
    ]
    for r in resultados:
        estado = "✔" if not r.fallas else f"✘ {r.fallas}"
        lineas += [f"## {estado} · {r.clienta.clave} — {r.clienta.como_escribe}", ""]
        if r.error:
            lineas += [f"**Se cortó:** {r.error}", ""]
        for paso, salida, problemas in r.pasos:
            dijo = (paso.lia and f"(Lía: {paso.lia})") or " / ".join(
                x
                for x in (
                    *(paso.rafaga or (paso.texto or "",)),
                    f"[foto {paso.foto}]" if paso.foto else "",
                    f"[vitrina {paso.producto}]" if paso.producto else "",
                )
                if x
            )
            lineas.append(f"- **{paso.etapa}** · ella: {dijo}")
            for t in salida.textos:
                lineas.append(f"  - bot: {t[:300].replace(chr(10), ' / ')}")
            for m in salida.medios:
                lineas.append(f"  - bot: [imagen {m}]")
            for p in problemas:
                lineas.append(f"  - ❌ {p}")
        lineas.append("")
    return "\n".join(lineas)


async def principal(solo: set[str]) -> int:
    prueba = Prueba()
    clientas = [c for c in CLIENTAS if not solo or c.clave in solo]
    print(f"\n  Prueba de verdad · {len(clientas)} clientas · base en {TEMPORAL}\n")
    inicio = time.monotonic()
    # A lo sumo `A_LA_VEZ` clientas escribiendo al mismo tiempo: a esta escala
    # (~40 ventas al mes) es lo que pasa en la vida real; con 18 a la vez la
    # fila del turno (uno a la vez, como en el servidor) se mide como lentitud.
    cupo = asyncio.Semaphore(A_LA_VEZ)

    async def con_cupo(c: Clienta) -> Resultado:
        async with cupo:
            return await prueba.clienta(c)

    resultados = await asyncio.gather(*(con_cupo(c) for c in clientas))
    if prueba.c.agrupador is not None:
        await prueba.c.agrupador.detener()
    usd, turnos = prueba.costo()
    texto = informe(list(resultados), usd, turnos, (time.monotonic() - inicio) / 60)
    print("\n" + texto)
    malos = sum(r.fallas for r in resultados)
    print(f"\n  {'TODO BIEN' if not malos else f'{malos} PASO(S) MAL'}\n")
    return 1 if malos else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="La prueba de verdad (IA real, aislada)")
    ap.add_argument("--solo", default="", help="claves separadas por coma")
    args = ap.parse_args()
    solo = {x.strip() for x in args.solo.split(",") if x.strip()}
    return asyncio.run(principal(solo))


if __name__ == "__main__":
    raise SystemExit(main())
