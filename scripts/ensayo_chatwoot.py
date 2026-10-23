"""Ensayo de punta a punta: WhatsApp → bot → Chatwoot → bot, sin gastar nada.

    vb ensayo

Prueba lo que las pruebas unitarias no alcanzan: el Chatwoot DE VERDAD (el de
docker/chatwoot) con su webhook, su agente bot y sus estados. Para no gastar ni
un peso y no tocar a nadie:

- levanta un SEGUNDO bot en el puerto 8001, con el modelo simulado (cero
  llamadas a Claude), el canal de consola (cero mensajes a Meta) y una base de
  datos temporal (la de verdad ni se entera);
- apunta el webhook de Chatwoot a ese bot mientras dura, y lo devuelve al
  terminar pase lo que pase. El bot real sigue atendiendo en el 8000;
- escribe como una clienta inventada (+57 000 000 0009) y al final la borra de
  Chatwoot.

Qué comprueba (lo que falló con clientas reales el 19/09):
  1. lo que escribe la clienta aparece UNA vez; lo del bot, firmado «VentaBot»,
     sin repetir, y la conversación asignada a VentaBot (la lleva el bot);
  2. el bot no se calla por su propio eco;
  3. «Asignar a mi» lo calla y la deja asignada a Lía;
  4. mientras Lía atiende, lo de la clienta llega pero el bot no contesta;
  5. lo que Lía escribe en Chatwoot sale hacia la clienta;
  6. «Resolver» NO se la devuelve al bot (09/10); la etiqueta
     «hacer-devolver-al-bot» sí, y vuelve a quedar asignada a VentaBot;
  7. pedir una persona pone «necesita-persona», la deja Urgente y le deja a
     Lía una nota privada con el porqué;
  8. la etiqueta «hacer-abono-ok» (lo que Lía pone desde el celular) pasa un
     pedido de verdad al taller, le avisa a la clienta, cambia la etapa, quita
     la etiqueta y deja una nota con el resultado.

Sale con código 0 solo si TODO pasó. Deja el detalle en logs/ensayo-chatwoot.log.

OJO: es para el Chatwoot del PC (plan B). En el servidor desviaría unos minutos
el webhook del Chatwoot de producción, por donde llegan las respuestas de Lía:
allá no se corre con clientas atendiendo.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.infra.consola import preparar_salida

# UTF-8 pase lo que pase: sin esto, redirigir la salida a un archivo (o
# leerla desde otro proceso) revienta en Windows al imprimir un ✔.
preparar_salida()


from app.infra.settings import Settings

PUERTO = 8001
BOT = f"http://127.0.0.1:{PUERTO}"
NUMERO = "570000000009"
CONV = f"wa:{NUMERO}"
NOMBRE = "ENSAYO VentaBot"
REGISTRO = RAIZ / "logs" / "ensayo-chatwoot.log"

V, R, A, B, RST = "\033[32m", "\033[31m", "\033[33m", "\033[1m", "\033[0m"


class Ensayo:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.api = f"{s.chatwoot_url}/api/v1/accounts/{s.chatwoot_account_id}"
        self.h = {"api_access_token": s.chatwoot_token}
        self.fallos: list[str] = []
        self.temporal = Path(tempfile.mkdtemp(prefix="ventabot-ensayo-"))
        self.base = self.temporal / "ensayo.db"

    # -- utilidades ---------------------------------------------------------

    def ok(self, cond: bool, que: str) -> None:
        print(f"    {V}✔{RST} {que}" if cond else f"    {R}✘ {que}{RST}")
        if not cond:
            self.fallos.append(que)

    def cw(self, metodo: str, ruta: str, **kw):
        r = httpx.request(metodo, f"{self.api}{ruta}", headers=self.h, timeout=20, **kw)
        r.raise_for_status()
        return r.json() if r.content else None

    def escribe_clienta(self, texto: str) -> int:
        valor = {
            "messaging_product": "whatsapp",
            "metadata": {
                "display_phone_number": "570000000000",
                "phone_number_id": self.s.wa_phone_number_id,
            },
            "contacts": [{"profile": {"name": NOMBRE}, "wa_id": NUMERO}],
            "messages": [
                {
                    "from": NUMERO,
                    "id": f"wamid.ENSAYO{uuid.uuid4().hex}",
                    "timestamp": str(int(time.time())),
                    "type": "text",
                    "text": {"body": texto},
                }
            ],
        }
        cuerpo = {
            "object": "whatsapp_business_account",
            "entry": [
                {"id": "ENSAYO", "changes": [{"field": "messages", "value": valor}]}
            ],
        }
        crudo = json.dumps(cuerpo).encode()
        firma = hmac.new(
            self.s.meta_app_secret.encode(), crudo, hashlib.sha256
        ).hexdigest()
        return httpx.post(
            f"{BOT}/webhook/whatsapp",
            content=crudo,
            timeout=30,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": f"sha256={firma}",
            },
        ).status_code

    def en_pausa(self) -> bool:
        import sqlite3

        with sqlite3.connect(str(self.base)) as cx:
            f = cx.execute(
                "SELECT payload FROM conv_contexto WHERE conversation_id = ?", (CONV,)
            ).fetchone()
        return bool(f and json.loads(f[0]).get("humano_hasta"))

    def salio(self, texto: str) -> bool:
        """¿El bot de ensayo mandó (o encoló) esto hacia la clienta?"""
        import sqlite3

        with sqlite3.connect(str(self.base)) as cx:
            filas = cx.execute(
                "SELECT payload FROM outbox WHERE destinatario = ?", (NUMERO,)
            ).fetchall()
        return any(texto in (p or "") for (p,) in filas)

    def conversacion(self) -> dict | None:
        for c in self.cw("GET", "/contacts/search", params={"q": CONV})["payload"]:
            if c.get("identifier") == CONV:
                convs = self.cw("GET", f"/contacts/{c['id']}/conversations")["payload"]
                return convs[0] if convs else None
        return None

    def mensajes(self, cid: int) -> list[dict]:
        return self.cw("GET", f"/conversations/{cid}/messages")["payload"]

    def estado(self, cid: int) -> str:
        return self.cw("GET", f"/conversations/{cid}")["status"]

    def quien(self, cid: int) -> str:
        """«AgentBot», «User» o «» (sin asignar)."""
        meta = self.cw("GET", f"/conversations/{cid}").get("meta") or {}
        return meta.get("assignee_type") or ""

    @staticmethod
    def esperar(cond, segundos: float = 30) -> bool:
        fin = time.time() + segundos
        while time.time() < fin:
            try:
                if cond():
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def del_bot(self, cid: int) -> list[dict]:
        return [
            m
            for m in self.mensajes(cid)
            if m["message_type"] == 1
            and (m.get("sender") or {}).get("type") == "agent_bot"
        ]

    # -- montaje ------------------------------------------------------------

    def borrar_clienta(self) -> None:
        for c in self.cw("GET", "/contacts/search", params={"q": CONV})["payload"]:
            if c.get("identifier") == CONV:
                self.cw("DELETE", f"/contacts/{c['id']}")

    def webhook(self) -> dict:
        datos = self.cw("GET", "/webhooks")["payload"]
        lista = datos.get("webhooks", []) if isinstance(datos, dict) else datos
        return next(w for w in lista if "/webhook/chatwoot" in (w.get("url") or ""))

    def apuntar_webhook(self, url: str) -> None:
        w = self.webhook()
        self.cw("PATCH", f"/webhooks/{w['id']}", json={"url": url})

    def arrancar_bot(self) -> subprocess.Popen:
        entorno = dict(os.environ)
        entorno.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "LLM_BACKEND": "fake",
                "CHANNEL_BACKEND": "console",
                "REPOSITORY_BACKEND": "sqlite",
                "SQLITE_PATH": str(self.base),
                "VENTAS_EXCEL": str(self.temporal / "ventas.xlsx"),
                "AVISOS_BACKEND": "ninguno",
                "RECORDATORIOS": "false",
                "TRANSCRIPCION_BACKEND": "ninguno",
                # Su registro va a logs/ensayo-chatwoot.log, no al del bot real.
                "LOG_ARCHIVO": "",
                # El ensayo no ensucia las trazas de producción en LangSmith.
                "LANGSMITH_TRACING": "false",
                "URL_PUBLICA": BOT,
                "PUBLIC_URL": BOT,
            }
        )
        REGISTRO.parent.mkdir(exist_ok=True)
        salida = REGISTRO.open("w", encoding="utf-8")
        proceso = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(PUERTO),
            ],
            cwd=RAIZ,
            env=entorno,
            stdout=salida,
            stderr=subprocess.STDOUT,
        )
        arriba = self.esperar(
            lambda: httpx.get(f"{BOT}/health", timeout=2).status_code == 200, 40
        )
        if not arriba:
            proceso.kill()
            raise RuntimeError(f"el bot de ensayo no arrancó: mira {REGISTRO}")
        return proceso

    # -- el ensayo ----------------------------------------------------------

    def correr(self) -> None:
        print(f"\n{B}1. La clienta escribe{RST}")
        self.ok(
            self.escribe_clienta("Hola, quiero un anillo") == 200, "WhatsApp la recibe"
        )
        self.ok(
            self.esperar(lambda: self.conversacion() is not None), "aparece en Chatwoot"
        )
        cv = self.conversacion()
        if cv is None:
            return
        cid = cv["id"]
        self.ok(self.esperar(lambda: self.del_bot(cid)), "la respuesta del bot aparece")
        time.sleep(4)  # que lleguen todas las piezas y los ecos
        ms = self.mensajes(cid)
        entrantes = [m for m in ms if m["message_type"] == 0]
        salientes = [m for m in ms if m["message_type"] == 1]
        self.ok(len(entrantes) == 1, f"lo de la clienta está UNA vez ({len(entrantes)})")
        self.ok(
            all((m.get("sender") or {}).get("type") == "agent_bot" for m in salientes),
            f"las {len(salientes)} piezas del bot van firmadas «VentaBot»",
        )
        textos = [m["content"] for m in salientes]
        self.ok(len(textos) == len(set(textos)), "ninguna pieza repetida")
        self.ok(
            self.esperar(lambda: self.quien(cid) == "AgentBot", 10),
            f"asignada a VentaBot ({self.quien(cid)}), igual en el PC y el celular",
        )
        self.ok(
            self.esperar(
                lambda: any(
                    e.startswith(("01-", "02-"))
                    for e in self.cw("GET", f"/conversations/{cid}/labels")["payload"]
                ),
                10,
            ),
            "tiene su etapa (01-consulta / 02-disenando)",
        )
        self.ok(not self.en_pausa(), "el bot NO se calló por su propio eco")

        print(f"\n{B}2. Lía se asigna la conversación{RST}")
        yo = httpx.get(
            f"{self.s.chatwoot_url}/api/v1/profile", headers=self.h, timeout=20
        ).json()["id"]
        self.cw("POST", f"/conversations/{cid}/assignments", json={"assignee_id": yo})
        self.ok(self.esperar(self.en_pausa, 15), "el bot se calla")
        self.ok(self.esperar(lambda: self.quien(cid) == "User", 15), "asignada a Lía")

        print(f"\n{B}3. La clienta escribe mientras la atiende Lía{RST}")
        antes = len(self.del_bot(cid))
        self.escribe_clienta("¿Y cuánto demora?")
        self.ok(
            self.esperar(
                lambda: any(
                    m["content"] == "¿Y cuánto demora?" for m in self.mensajes(cid)
                )
            ),
            "su mensaje aparece en Chatwoot",
        )
        time.sleep(3)
        self.ok(len(self.del_bot(cid)) == antes, "el bot no contesta encima")

        print(f"\n{B}4. Lía contesta desde Chatwoot{RST}")
        self.cw(
            "POST",
            f"/conversations/{cid}/messages",
            json={"content": "Hola, soy Lía (ensayo)", "message_type": "outgoing"},
        )
        self.ok(
            self.esperar(lambda: self.salio("soy Lía (ensayo)"), 15),
            "sale hacia la clienta",
        )
        time.sleep(2)
        self.ok(self.en_pausa(), "el bot sigue callado")

        print(f"\n{B}5. Lía resuelve: resolver NO devuelve al bot (09/10){RST}")
        self.cw(
            "POST", f"/conversations/{cid}/toggle_status", json={"status": "resolved"}
        )
        time.sleep(3)
        self.ok(self.en_pausa(), "el bot sigue callado: resolver es solo cerrar")

        print(f"\n{B}5b. Lía la devuelve al bot (etiqueta){RST}")
        self.cw(
            "POST",
            f"/conversations/{cid}/labels",
            json={"labels": ["hacer-devolver-al-bot"]},
        )
        self.ok(self.esperar(lambda: not self.en_pausa(), 15), "el bot vuelve a atender")
        self.ok(
            self.esperar(lambda: self.quien(cid) == "AgentBot", 15),
            "asignada otra vez a VentaBot",
        )
        antes = len(self.del_bot(cid))
        self.escribe_clienta("Listo, ¿cómo pago?")
        self.ok(
            self.esperar(lambda: len(self.del_bot(cid)) > antes), "contesta el siguiente"
        )

        print(f"\n{B}6. La clienta pide una persona{RST}")
        self.escribe_clienta("Quiero hablar con una persona")
        self.ok(
            self.esperar(
                lambda: (
                    "necesita-persona"
                    in (self.cw("GET", f"/conversations/{cid}/labels")["payload"] or [])
                )
            ),
            "etiqueta «necesita-persona»",
        )
        self.ok(
            self.esperar(
                lambda: (
                    self.cw("GET", f"/conversations/{cid}").get("priority") == "urgent"
                ),
                15,
            ),
            "queda URGENTE (la sigue atendiendo VentaBot mientras tanto)",
        )
        self.ok(
            self.esperar(
                lambda: any(
                    m.get("private") and "🙋" in (m.get("content") or "")
                    for m in self.mensajes(cid)
                ),
                15,
            ),
            "nota privada de VentaBot: por qué la necesita",
        )

        print(f"\n{B}7. Lía verifica el abono desde Chatwoot (etiqueta){RST}")
        pedido_id = self.crear_pedido_en_revision()
        self.cw(
            "POST", f"/conversations/{cid}/labels", json={"labels": ["hacer-abono-ok"]}
        )
        self.ok(
            self.esperar(
                lambda: self.estado_del_pedido(pedido_id) == "EN_PRODUCCION", 20
            ),
            "el pedido pasa al taller",
        )
        etiquetas = lambda: self.cw("GET", f"/conversations/{cid}/labels")["payload"]  # noqa: E731
        self.ok(
            self.esperar(
                lambda: (
                    "05-en-taller" in etiquetas() and "hacer-abono-ok" not in etiquetas()
                ),
                20,
            ),
            "etapa «05-en-taller» y la etiqueta de la orden se quita sola",
        )
        self.ok(
            self.salio("taller"), "a la clienta le sale el aviso de que entró al taller"
        )
        self.ok(
            any(
                m.get("private") and "✅" in (m.get("content") or "")
                for m in self.mensajes(cid)
            ),
            "nota privada con el resultado",
        )

    def crear_pedido_en_revision(self) -> str:
        """Un pedido completo de la clienta de ensayo, con el abono en revisión."""
        from app.adapters.repositories.sqlite_store import (
            SqliteCustomerRepository,
            SqliteDB,
            SqliteOrderRepository,
        )
        from app.domain.envio import DatosDeEnvio
        from app.domain.models import Channel, Customer, Order, OrderItem
        from app.domain.personalizacion import ColorCircon, Huellita, Personalizacion

        db = SqliteDB(self.base)
        clientes = SqliteCustomerRepository(db)
        cliente = clientes.get_by_channel_user(
            Channel.WHATSAPP.value, NUMERO
        ) or clientes.upsert(Customer(channel=Channel.WHATSAPP, channel_user_id=NUMERO))
        diseno = Personalizacion(
            talla=7,
            huellitas=[Huellita(corazon=ColorCircon.ROSADO, dedos=ColorCircon.ROSADO)],
            grabados=["Roberto"],
        )
        pedido = SqliteOrderRepository(db).create(
            Order(
                codigo="PED-ENSAYO-01",
                customer_id=cliente.id,
                estado="EN_REVISION_PAGO",
                items=[
                    OrderItem(
                        sku="ANI-HUE-1",
                        nombre="Anillo huellita x1",
                        cantidad=1,
                        precio_unitario_cop=200_000,
                        personalizacion=diseno,
                    )
                ],
                total_cop=200_000,
                anticipo_cop=60_000,
                saldo_cop=140_000,
                envio=DatosDeEnvio(
                    nombre=NOMBRE, ciudad="Bogotá", direccion="Calle 45 #12-30"
                ),
            ),
            idem_key="ensayo-pedido",
        )
        db.cerrar()
        return pedido.id

    def estado_del_pedido(self, pedido_id: str) -> str:
        import sqlite3

        with sqlite3.connect(str(self.base)) as cx:
            fila = cx.execute(
                "SELECT estado FROM orders WHERE id = ?", (pedido_id,)
            ).fetchone()
        return fila[0] if fila else ""

    def todo(self) -> int:
        print(f"\n{B}ENSAYO CHATWOOT{RST}  (bot de ensayo en :{PUERTO}, modelo simulado,")
        print("                 sin Meta, base temporal; el bot real sigue en :8000)")
        original = self.webhook()["url"]
        token = original.split("token=", 1)[-1]
        self.borrar_clienta()
        proceso = self.arrancar_bot()
        try:
            self.apuntar_webhook(
                f"http://host.docker.internal:{PUERTO}/webhook/chatwoot?token={token}"
            )
            self.correr()
        finally:
            self.apuntar_webhook(original)
            proceso.terminate()
            try:
                proceso.wait(10)
            except subprocess.TimeoutExpired:
                proceso.kill()
            self.borrar_clienta()
            import shutil

            shutil.rmtree(self.temporal, ignore_errors=True)
        devuelto = self.webhook()["url"] == original
        self.ok(devuelto, "webhook devuelto al bot real")
        if self.fallos:
            print(f"\n{R}{B}{len(self.fallos)} FALLO(S){RST} · detalle en {REGISTRO}")
            return 1
        print(f"\n{V}{B}TODO BIEN{RST} · clienta de ensayo borrada, bot real intacto")
        return 0


def main() -> int:
    s = Settings()
    if not (s.chatwoot_url and s.chatwoot_token and s.chatwoot_webhook_token):
        print("Chatwoot no está conectado: corre  vb chatwoot --conectar")
        return 1
    return Ensayo(s).todo()


if __name__ == "__main__":
    sys.exit(main())
