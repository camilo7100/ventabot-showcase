#!/usr/bin/env python3
"""EL DIAGNÓSTICO: revisa TODO de punta a punta y dice cómo quedó.

    vb diagnostico              # revisa todo y lo cuenta
    vb diagnostico --rapido     # sin tests ni lint (3 s en vez de 40)
    vb diagnostico --ventana    # además, una ventanita con el resultado
    vb diagnostico --json       # para máquinas

════════════════════════════════════════════════════════════════════════════
POR QUÉ ESTO EXISTE
════════════════════════════════════════════════════════════════════════════
El bot tiene ocho piezas que se pueden romper por separado y en silencio: el
servidor, el túnel, Chatwoot, el ERP, LangSmith, la transcripción de las notas
de voz, la base y las credenciales. Cuando una falla, el síntoma siempre es el
mismo —«no me llegan los mensajes»— y averiguar cuál es cuesta media hora.

Esto lo hace en menos de un minuto y dice EN CLARO cuál está rota y qué
comando la arregla. Se corre antes de cada jornada y después de cada cambio.

Regla: si algo aquí sale en rojo, el bot NO está listo para atender.

Cada revisión deja su resultado en logs/diagnostico.log, así se puede ver qué
cambió entre una corrida y la anterior.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# Las herramientas del entorno (ruff, pytest) van primero en el PATH, aunque
# nadie haya «activado» el .venv.
os.environ["PATH"] = (
    str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
)
sys.path.insert(0, str(RAIZ))

from app.infra.consola import preparar_salida

# UTF-8 pase lo que pase: sin esto, redirigir la salida a un archivo (o
# leerla desde otro proceso) revienta en Windows al imprimir un ✔.
_C = preparar_salida()
V, R, A, G, C, B, RST = (
    _C.ok,
    _C.error,
    _C.aviso,
    _C.tenue,
    _C.titulo,
    _C.fuerte,
    _C.fin,
)
OK, MAL, OJO = f"{V}✔{RST}", f"{R}✘{RST}", f"{A}○{RST}"

from app.infra.settings import get_settings

REGISTRO = RAIZ / "logs" / "diagnostico.log"
#: ¿Corre dentro del contenedor del servidor (Oracle) o en el PC? En el
#: servidor ngrok vive en su propio contenedor, Docker no se ve desde adentro y
#: las pruebas no van en la imagen: esas revisiones miran otra cosa (25/09).
EN_EL_SERVIDOR = Path("/.dockerenv").exists()
#: Cuánto se espera a cada servicio. Generoso con Chatwoot (Rails despierta
#: despacio) y corto con lo local.
ESPERA = 20


def _sin_secretos(texto: str) -> str:
    """Tapa cualquier token que venga en una URL: esto se lee en voz alta."""
    return re.sub(r"(token=|secret=|key=)[^&\s]+", r"•••", texto or "")


@dataclass
class Resultado:
    """Una revisión: cómo salió, qué se vio y qué hacer si salió mal."""

    grupo: str
    nombre: str
    estado: str  # "ok" | "mal" | "ojo"
    detalle: str = ""
    arreglo: list[str] = field(default_factory=list)


#: Cuánto se espera a que ngrok termine de publicar, en segundos.
ESPERA_DEL_TUNEL_S = 20


def _insistiendo(mirar, bien, segundos: int = ESPERA_DEL_TUNEL_S):
    """Mira hasta que esté bien o se acabe el tiempo. Devuelve lo último visto.

    No es disimular un fallo: si de verdad está roto, se agotan los segundos y
    se reporta igual. Es no gritar antes de que termine de arrancar.
    """
    limite = time.monotonic() + segundos
    while True:
        try:
            visto = mirar()
            if bien(visto):
                return visto
        except Exception:
            # Recién arrancado, ngrok todavía no abre ni su propio 4040. Eso
            # no es «ngrok no está corriendo»: es que no ha terminado.
            if time.monotonic() >= limite:
                raise
            visto = None
        if time.monotonic() >= limite:
            return visto
        time.sleep(2)


class Diagnostico:
    def __init__(self, rapido: bool = False) -> None:
        self.s = get_settings()
        self.rapido = rapido
        self.r: list[Resultado] = []

    # -- utilidades ---------------------------------------------------------

    def anota(self, grupo, nombre, estado, detalle="", arreglo=()) -> Resultado:
        res = Resultado(grupo, nombre, estado, detalle, list(arreglo))
        self.r.append(res)
        icono = {"ok": OK, "mal": MAL, "ojo": OJO}[estado]
        print(f"  {icono} {nombre}" + (f"  {G}{detalle}{RST}" if detalle else ""))
        for a in res.arreglo:
            print(f"      {A}→{RST} {a}")
        return res

    def _la_ia(self, s) -> None:
        """Los dos proveedores, en el orden en que se usan, y si hay clientas
        esperando porque ninguno contestó."""
        self.anota(
            "claves",
            "Claude (Anthropic)",
            "ok" if s.anthropic_api_key else "mal",
            f"{s.llm_basico_model} · cuando duda {s.llm_fuerte_model}"
            if s.anthropic_api_key
            else "sin ANTHROPIC_API_KEY",
        )
        con_gpt = s.llm_respaldo_backend == "openai"
        if con_gpt:
            listo = bool(s.openai_api_key and s.openai_modelo)
            fuerte = s.openai_modelo_fuerte or s.openai_modelo
            esfuerzo_fuerte = s.openai_esfuerzo_fuerte or s.openai_esfuerzo
            self.anota(
                "claves",
                "GPT (OpenAI)",
                "ok" if listo else "mal",
                f"{s.openai_modelo} ({s.openai_esfuerzo or 'de fábrica'}) · cuando "
                f"duda {fuerte} ({esfuerzo_fuerte or 'de fábrica'})"
                if listo
                else "falta OPENAI_API_KEY u OPENAI_MODELO",
            )
        gpt_primero = con_gpt and s.ia_principal == "openai"
        orden = ["GPT", "Claude"] if gpt_primero else ["Claude"] + ["GPT"] * con_gpt
        self.anota(
            "claves",
            "Quién contesta",
            "ok" if len(orden) == 2 else "ojo",
            " → si no contesta → ".join(orden)
            + f" (insiste {s.ia_paciencia_s:.0f} s; luego reintenta solo)",
            [] if len(orden) == 2 else ["Con un solo proveedor no hay respaldo"],
        )
        try:
            import sqlite3

            with sqlite3.connect(str(s.sqlite_path)) as cx:
                esperando = cx.execute(
                    "SELECT COUNT(*) FROM conv_contexto "
                    "WHERE json_extract(payload, '$.pendiente_ia') IS NOT NULL"
                ).fetchone()[0]
                llamadas = self._llamadas_de_las_24_horas(cx)
        except Exception:
            return
        self.anota(
            "claves",
            "Clientas esperando porque la IA se cayó",
            "ojo" if esperando else "ok",
            f"{esperando} (el bot les contesta solo cuando vuelva)" if esperando else "0",
        )
        self._la_cache(llamadas)

    @staticmethod
    def _llamadas_de_las_24_horas(cx) -> list[dict]:
        from datetime import UTC, datetime, timedelta

        desde = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        filas = cx.execute(
            "SELECT payload FROM decisiones WHERE ts >= ?", (desde,)
        ).fetchall()
        llamadas = [ll for (p,) in filas for ll in json.loads(p).get("llm_calls", [])]
        return [ll for ll in llamadas if ll.get("ok")]

    def _la_cache(self, llamadas: list[dict]) -> None:
        """¿El prompt fijo de la asesora sale de caché? Medido con los turnos
        REALES de las últimas 24 h, no con una llamada de prueba: la caché solo
        sirve si se reutiliza entre clientas.

        Sin caché, cada turno paga ~9.000 tokens de prompt a precio entero (10
        veces más con GPT y con Claude). Se rompe sin avisar si algo que cambia
        en cada turno (una hora, un nombre) se cuela en el prompt del sistema.
        """
        if not llamadas:
            self.anota("claves", "la caché de la IA", "ok", "sin turnos en 24 h")
            return
        entrada = sum(ll.get("in", 0) + ll.get("cache_read", 0) for ll in llamadas)
        de_cache = sum(ll.get("cache_read", 0) for ll in llamadas)
        parte = de_cache / entrada if entrada else 0.0
        usd = sum(ll.get("usd", 0.0) for ll in llamadas)
        mal = len(llamadas) >= 5 and parte < 0.5
        self.anota(
            "claves",
            "la caché de la IA",
            "ojo" if mal else "ok",
            f"{parte:.0%} de lo que lee sale de caché · {len(llamadas)} llamadas · "
            f"US${usd:.3f} en 24 h",
            ["Algo que cambia en cada turno se coló en el prompt del sistema"]
            if mal
            else [],
        )

    def titulo(self, texto: str) -> None:
        print(f"\n{B}{texto}{RST}")

    @staticmethod
    def _get(url: str, **kw):
        import httpx

        return httpx.get(url, timeout=ESPERA, **kw)

    def _cw(self, ruta: str):
        """Una llamada a la API de Chatwoot con el token de Lía."""
        api = f"{self.s.chatwoot_url}/api/v1/accounts/{self.s.chatwoot_account_id}"
        r = self._get(f"{api}{ruta}", headers={"api_access_token": self.s.chatwoot_token})
        r.raise_for_status()
        return r.json()

    # ── 1. El servidor ─────────────────────────────────────────────────────

    def servidor(self) -> None:
        self.titulo("1. EL BOT")
        try:
            r = self._get("http://127.0.0.1:8000/health")
            d = r.json()
        except Exception as e:
            self.anota(
                "bot",
                "el servidor responde",
                "mal",
                str(e)[:70],
                ["Doble clic en ENCENDER-BOT.cmd"],
            )
            return
        self.anota(
            "bot",
            "el servidor responde",
            "ok",
            # `llm` es LLM_BACKEND: `claude` quiere decir «IA en línea» (GPT y
            # Claude, en el orden de «Quién contesta»); `fake`, sin IA.
            f"canal={d.get('canal')} · "
            f"ia={'en línea' if d.get('llm') == 'claude' else d.get('llm')}"
            f" · datos={d.get('repositorio')}",
        )
        pendientes = d.get("pendientes_en_outbox", 0)
        self.anota(
            "bot",
            "la bandeja de salida está al día",
            "ok" if pendientes == 0 else "ojo",
            f"{pendientes} sin salir · {d.get('enviados', 0)} enviados",
            []
            if pendientes == 0
            else ["Mira la ventana SERVIDOR: algo no está saliendo"],
        )
        # EL SERVIDOR ZOMBI. El 20/09 un uvicorn de hacía una hora seguía
        # con el puerto 8000 y el que se acababa de encender no podía
        # tomarlo: se reiniciaba en bucle, callado. El bot contestó una hora
        # con el código de anoche y por fuera todo se veía en verde.
        self._servidor_al_dia(d.get("arrancado", ""))
        # El panel del taller: que esté cerrado con llave, no que esté abierto.
        try:
            sin_llave = self._get("http://127.0.0.1:8000/panel").status_code
            self.anota(
                "bot",
                "el panel pide contraseña",
                "ok" if sin_llave in (401, 403, 404) else "mal",
                f"sin token responde {sin_llave}",
                [] if sin_llave in (401, 403, 404) else ["PANEL_TOKEN vacío en .env"],
            )
        except Exception as e:
            self.anota("bot", "el panel pide contraseña", "ojo", str(e)[:60])

    def _servidor_al_dia(self, arrancado: str) -> None:
        """Que el servidor vivo sea más nuevo que el código que hay en disco."""
        if not arrancado:
            self.anota(
                "bot",
                "el servidor corre el código de ahora",
                "mal",
                "es una versión vieja: ni siquiera sabe decir cuándo arrancó",
                ["APAGAR-BOT.cmd y luego ENCENDER-BOT.cmd"],
            )
            return
        from datetime import datetime

        desde = datetime.fromisoformat(arrancado).astimezone()
        fuentes = [
            f
            for carpeta in ("app", "config")
            for f in (RAIZ / carpeta).rglob("*")
            if f.suffix in (".py", ".txt", ".yaml") and "__pycache__" not in f.parts
        ]
        nuevos = [
            f
            for f in fuentes
            if datetime.fromtimestamp(f.stat().st_mtime).astimezone() > desde
        ]
        cuantos = len(nuevos)
        self.anota(
            "bot",
            "el servidor corre el código de ahora",
            "ok" if not nuevos else "mal",
            f"arrancó {desde:%d/%m %H:%M}"
            + (f" · {cuantos} archivo(s) cambiados después" if nuevos else ""),
            []
            if not nuevos
            else [
                f"{nuevos[0].relative_to(RAIZ)} es más nuevo que el servidor"
                + (f" (y {cuantos - 1} más)" if cuantos > 1 else ""),
                "Está atendiendo con código viejo: APAGAR-BOT.cmd y ENCENDER-BOT.cmd",
            ],
        )
        self._un_solo_servidor()

    def _un_solo_servidor(self) -> None:
        """Dos servidores a la vez = el segundo no puede tomar el puerto."""
        # Solo procesos de Python. Cualquier consola que tenga ese texto en su
        # línea de comando (el propio PowerShell que pregunta, una terminal con
        # el comando escrito) se contaría a sí misma y daría un falso «hay dos
        # servidores», que es justo el aviso que no puede mentir.
        guion = (
            "(Get-CimInstance Win32_Process | Where-Object "
            "{ $_.Name -like 'python*' "
            "-and $_.CommandLine -match 'uvicorn app.api.main' }).Count"
        )
        try:
            salida = subprocess.run(
                ["powershell", "-NoProfile", "-Command", guion],
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout.strip()
            cuantos = int(salida or 0)
        except Exception:
            return  # sin PowerShell no se concluye nada
        # Son dos por servidor: el lanzador del .venv y el Python de verdad.
        sobran = cuantos > 2
        self.anota(
            "bot",
            "hay UN solo servidor",
            "mal" if sobran else "ok",
            f"{cuantos} proceso(s) de uvicorn",
            []
            if not sobran
            else [
                "Hay un servidor viejo vivo: el nuevo no puede tomar el puerto 8000",
                "APAGAR-BOT.cmd (espera a que diga «Listo») y ENCENDER-BOT.cmd",
            ],
        )

    # ── 2. El túnel ────────────────────────────────────────────────────────

    def tunel(self) -> None:
        self.titulo("2. EL TÚNEL (lo que ve internet)")
        publica = self.s.url_publica
        if not publica:
            self.anota(
                "tunel",
                "hay una URL pública",
                "mal",
                "PUBLIC_URL vacío",
                ["Pon PUBLIC_URL en .env con el dominio de ngrok"],
            )
            return

        def publicados() -> set[str]:
            r = self._get("http://127.0.0.1:4040/api/tunnels")
            return {t["public_url"] for t in r.json()["tunnels"]}

        if EN_EL_SERVIDOR:
            # ngrok corre en su propio contenedor: su 4040 no se ve desde aquí.
            # Lo que importa es que internet llegue, y eso se mira abajo.
            # En el servidor entra Caddy con el dominio propio: lo que importa
            # es que internet llegue, y eso se mira aquí mismo.
            self._desde_internet(publica)
            return
        try:
            # ngrok tarda unos segundos en publicar la entrada del dominio. Ahí
            # en medio contesta su propia página de «esto no existe» (404), y
            # el diagnóstico daba dos rojos que diez segundos después estaban
            # en verde (20/09). Una falsa alarma enseña a no creerle.
            vivos = _insistiendo(publicados, lambda v: publica in v)
        except Exception:
            self.anota(
                "tunel",
                "ngrok está corriendo",
                "mal",
                "no responde en el 4040",
                ["Abre la ventana VentaBot - TUNEL (o ENCENDER-BOT.cmd)"],
            )
            return
        self.anota("tunel", "ngrok está corriendo", "ok", f"{len(vivos)} entrada(s)")
        self.anota(
            "tunel",
            "el dominio de .env es el que está publicado",
            "ok" if publica in vivos else "mal",
            publica,
            []
            if publica in vivos
            else [
                "ngrok arrancó con otro dominio: Meta entrega a un sitio muerto",
                "Cierra la ventana TUNEL y vuelve a ENCENDER-BOT.cmd",
            ],
        )
        self._desde_internet(publica)

    def _desde_internet(self, publica: str) -> None:
        # Con dominio propio Chatwoot tiene el suyo; con ngrok comparte el del bot.
        chatwoot = (self.s.chatwoot_url_publica or publica).rstrip("/")
        for nombre, url, espera in (
            ("el bot se ve desde internet", f"{publica}/health", 200),
            (
                "Chatwoot se ve desde internet (la app del celular)",
                f"{chatwoot}/api",
                200,
            ),
        ):
            try:
                codigo = _insistiendo(
                    lambda u=url: self._get(u).status_code,
                    lambda c, e=espera: c == e,
                )
            except Exception as e:
                codigo, extra = 0, str(e)[:50]
            else:
                extra = f"HTTP {codigo}"
            self.anota(
                "tunel",
                nombre,
                "ok" if codigo == espera else "mal",
                extra,
                [] if codigo == espera else [f"No responde {url}"],
            )

    def _llegan_las_trazas(self, s) -> None:
        """¿LangSmith está RECIBIENDO los turnos? Encendido no es lo mismo que
        llegando (12/10): una clave vencida o un proyecto mal escrito no se ven
        en la configuración. Se comparan los turnos de las últimas 24 h con las
        trazas «turno» que tiene LangSmith en ese tiempo."""
        import httpx

        desde = datetime.now(UTC) - timedelta(hours=24)
        base = Path(s.sqlite_path)
        turnos = 0
        if base.exists():
            with sqlite3.connect(str(base)) as cx, contextlib.suppress(sqlite3.Error):
                turnos = cx.execute(
                    "SELECT COUNT(*) FROM decisiones WHERE ts >= ?",
                    (desde.isoformat(),),
                ).fetchone()[0]
        api = (s.langsmith_endpoint or "https://api.smith.langchain.com").rstrip("/")
        h = {"x-api-key": s.langsmith_api_key}
        try:
            proyectos = httpx.get(
                f"{api}/api/v1/sessions",
                params={"name": s.langsmith_project},
                headers=h,
                timeout=15,
            ).json()
            if not proyectos:
                raise ValueError(f"no existe el proyecto «{s.langsmith_project}»")
            r = httpx.post(
                f"{api}/api/v1/runs/query",
                json={
                    "session": [proyectos[0]["id"]],
                    "start_time": desde.isoformat(),
                    "is_root": True,
                    "limit": 100,
                    "select": ["name", "error"],
                },
                headers=h,
                timeout=15,
            )
            r.raise_for_status()
            corridas = r.json().get("runs", [])
        except Exception as e:
            self.anota(
                "claves",
                "LangSmith recibe los turnos",
                "ojo",
                f"no se pudo preguntar: {str(e)[:60]}",
                ["vb trazas (manda una de prueba y dice si llegó)"],
            )
            return
        de_turno = [c for c in corridas if c.get("name") == "turno"]
        con_error = sum(1 for c in de_turno if c.get("error"))
        bien = bool(de_turno) or turnos == 0
        self.anota(
            "claves",
            "LangSmith recibe los turnos",
            "ok" if bien else "ojo",
            f"{len(de_turno)}{'+' if len(corridas) >= 100 else ''} trazas de turno en "
            f"24 h ({turnos} turnos en la base)"
            + (f" · {con_error} con error" if con_error else ""),
            [] if bien else ["Hubo turnos y no llegó ninguna traza: vb trazas"],
        )

    def _el_esquema_de_la_jugada(self, s) -> None:
        """¿La API acepta el esquema con el que el bot piensa?

        El 20/09 un campo de más en `Jugada` hizo que contestara «Schema is too
        complex» a TODAS las llamadas. El bot arrancaba, el diagnóstico daba 36
        en verde y los tests pasaban —ninguno llama a la API—; lo único que se
        veía era que cada clienta recibía «Dame un momentico y te confirmo».

        Un esquema que la API no acepta es el bot apagado, así que se comprueba
        usándolo. Cuesta unos tokens y deja la gramática compilada, que es lo
        que el arranque necesita de todas formas.
        """
        if s.llm_respaldo_backend == "openai" and s.openai_api_key and s.openai_modelo:
            self._el_esquema_en_gpt(s)
        if not s.anthropic_api_key:
            return
        try:
            import anthropic

            from app.domain.asesora import Jugada

            cliente = anthropic.Anthropic(
                api_key=s.anthropic_api_key,
                max_retries=0,
                # Un esquema nuevo tarda en compilar la gramática (62 s medidos
                # el 20/09). Aquí no hay ninguna clienta esperando.
                timeout=180.0,
            )
            cliente.messages.parse(
                model=s.llm_basico_model,
                max_tokens=700,
                system=[{"type": "text", "text": "Eres Lía."}],
                messages=[{"role": "user", "content": "hola"}],
                output_format=Jugada,
            )
        except Exception as exc:
            detalle = str(exc)
            complejo = "too complex" in detalle
            self.anota(
                "claves",
                "el esquema de la asesora lo acepta la API",
                "mal",
                "Schema is too complex" if complejo else type(exc).__name__,
                [
                    "El bot NO puede pensar: cada clienta recibiría «dame un momentico»",
                    "Quita un campo de `Jugada` o de `CambiosDelBorrador`"
                    if complejo
                    else f"Revisa la conexión con Claude ({detalle[:70]})",
                ],
            )
            return
        self.anota(
            "claves",
            "el esquema de la asesora lo acepta Claude",
            "ok",
            "la gramática quedó compilada",
        )

    def _el_esquema_en_gpt(self, s) -> None:
        """Lo mismo que con Claude, pero en GPT: una llamada de verdad con el
        esquema `Jugada` y el MISMO adaptador de producción (modelo, esfuerzo,
        retención de la caché): si la API deja de aceptar algo, se ve aquí."""
        try:
            from app.adapters.llm.openai_client import OpenAILLM
            from app.domain.asesora import Jugada

            OpenAILLM(
                s.openai_modelo, s.openai_api_key, esfuerzo=s.openai_esfuerzo
            ).extract("Eres Lía.", "hola", Jugada)
        except Exception as exc:
            self.anota(
                "claves",
                "el esquema de la asesora lo acepta GPT",
                "mal",
                type(exc).__name__,
                [f"GPT no puede pensar: contestará Claude ({str(exc)[:70]})"],
            )
            return
        self.anota(
            "claves", "el esquema de la asesora lo acepta GPT", "ok", s.openai_modelo
        )

    # ── 3. Chatwoot ────────────────────────────────────────────────────────

    def chatwoot(self) -> None:
        self.titulo("3. CHATWOOT (el CRM)")
        if not (self.s.chatwoot_url and self.s.chatwoot_token):
            self.anota(
                "crm",
                "configurado",
                "mal",
                "faltan CHATWOOT_URL o CHATWOOT_TOKEN",
                ["vb chatwoot --conectar"],
            )
            return
        if EN_EL_SERVIDOR:
            # Desde el contenedor no se ve Docker: se le pregunta a Chatwoot.
            try:
                codigo = self._get(f"{self.s.chatwoot_url}/api").status_code
            except Exception as e:
                codigo, extra = 0, str(e)[:50]
            else:
                extra = f"HTTP {codigo}"
            self.anota(
                "crm",
                "Chatwoot responde",
                "ok" if codigo == 200 else "mal",
                extra,
                [] if codigo == 200 else ["En el servidor: docker compose ps"],
            )
        else:
            self._contenedores_del_pc()
        self._chatwoot_por_dentro()
        self._copias_pendientes()

    def _copias_pendientes(self) -> None:
        """Lo que falta por llegar a Chatwoot (la cola en la base, 07/10).

        Unas pocas de hace segundos es lo normal. Viejas = Chatwoot no está
        recibiendo (llegarán solas cuando vuelva). Apartadas = Chatwoot las
        rechazó y hay que mirarlas."""
        base = Path(self.s.sqlite_path)
        if not base.exists():
            return
        cx = sqlite3.connect(str(base))
        try:
            existe = cx.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='chatwoot_pendientes'"
            ).fetchone()
            if not existe:
                self.anota("crm", "copias pendientes", "ok", "ninguna")
                return
            esperando, mas_vieja = cx.execute(
                "SELECT COUNT(*), MIN(creada) FROM chatwoot_pendientes WHERE apartada = 0"
            ).fetchone()
            apartadas = cx.execute(
                "SELECT COUNT(*) FROM chatwoot_pendientes WHERE apartada = 1"
            ).fetchone()[0]
        finally:
            cx.close()
        minutos = 0
        if mas_vieja:
            minutos = int(
                (datetime.now(UTC) - datetime.fromisoformat(mas_vieja)).total_seconds()
                // 60
            )
        estado = "ok" if minutos < 10 and not apartadas else "ojo"
        detalle = f"{esperando} esperando" + (
            f" (la más vieja, de hace {minutos} min)" if esperando else ""
        )
        if apartadas:
            detalle += f" · {apartadas} rechazada(s) por Chatwoot"
        self.anota(
            "crm",
            "copias pendientes",
            estado,
            detalle,
            []
            if estado == "ok"
            else [
                "Viejas: Chatwoot no recibe; llegan solas cuando vuelva.",
                "Rechazadas: SELECT ultimo_error FROM chatwoot_pendientes "
                "WHERE apartada = 1",
            ],
        )

    def _contenedores_del_pc(self) -> None:
        try:
            salida = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout
        except Exception:
            salida = ""
        cajas = [ln for ln in salida.splitlines() if ln.startswith("chatwoot-")]
        arriba = [ln for ln in cajas if "\tUp" in ln or " Up " in ln.replace("\t", " ")]
        version = ""
        for ln in cajas:
            if m := re.search(r"chatwoot/chatwoot:(\S+)", ln):
                version = m.group(1)
        self.anota(
            "crm",
            "los contenedores están arriba",
            "ok" if len(arriba) >= 4 else "mal",
            f"{len(arriba)}/4 · {version}",
            [] if len(arriba) >= 4 else ["vb chatwoot (los levanta)"],
        )

    def _chatwoot_por_dentro(self) -> None:
        try:
            perfil = self._get(
                f"{self.s.chatwoot_url}/api/v1/profile",
                headers={"api_access_token": self.s.chatwoot_token},
            ).json()
            self.anota("crm", "el token de Lía sirve", "ok", perfil.get("email", ""))
        except Exception as e:
            self.anota(
                "crm",
                "el token de Lía sirve",
                "mal",
                str(e)[:60],
                ["vb chatwoot --conectar"],
            )
            return

        # El webhook: la razón nº 1 de «no me llegan los mensajes al CRM».
        try:
            datos = self._cw("/webhooks")["payload"]
            lista = datos.get("webhooks", []) if isinstance(datos, dict) else datos
            mio = next(
                (w for w in lista if "/webhook/chatwoot" in (w.get("url") or "")), None
            )
        except Exception as e:
            mio = None
            self.anota("crm", "webhook hacia el bot", "mal", str(e)[:60])
        if mio is not None:
            eventos = set(mio.get("subscriptions") or [])
            faltan = {"message_created", "conversation_updated"} - eventos
            self.anota(
                "crm",
                "webhook hacia el bot",
                "ok" if not faltan else "mal",
                _sin_secretos(mio.get("url", "")),
                [] if not faltan else [f"le faltan eventos: {', '.join(sorted(faltan))}"],
            )
        elif "webhook hacia el bot" not in [x.nombre for x in self.r]:
            self.anota(
                "crm",
                "webhook hacia el bot",
                "mal",
                "no existe",
                ["vb chatwoot --conectar"],
            )

        # El agente bot conectado al buzón: sin esto, 401 al copiar los mensajes.
        try:
            buzones = self._cw("/inboxes")["payload"]
            buzon = next(
                (b for b in buzones if b["id"] == self.s.chatwoot_inbox_id), None
            ) or (buzones[0] if buzones else None)
            self.anota(
                "crm",
                "el buzón existe y el bot está conectado",
                "ok" if buzon else "mal",
                (buzon or {}).get("name", ""),
                [] if buzon else ["vb chatwoot --conectar"],
            )
            if buzon and buzon.get("enable_auto_assignment"):
                self.anota(
                    "crm",
                    "auto-asignación apagada",
                    "mal",
                    "está encendida: el bot se callaría en cada charla nueva",
                    ["vb chatwoot --conectar"],
                )
            elif buzon:
                self.anota("crm", "auto-asignación apagada", "ok")
        except Exception as e:
            self.anota(
                "crm", "el buzón existe y el bot está conectado", "mal", str(e)[:60]
            )

        # 19/09: Chatwoot 4.x no entrega webhooks a direcciones privadas y el bot
        # ES una direccion privada. Bloqueaba TODO lo que vuelve del CRM (las
        # respuestas de Lía, «Asignar a mí», las etiquetas hacer-…) y en el CRM
        # no se veía ni un error: solo dejaba de funcionar.
        privado = any(
            x in (self.s.chatwoot_url or "") or x in ((mio or {}).get("url") or "")
            for x in ("localhost", "127.0.0.1", "host.docker.internal", "192.168.")
        )
        permite = ""
        try:
            permite = subprocess.run(
                [
                    "docker",
                    "exec",
                    "chatwoot-sidekiq-1",
                    "sh",
                    "-c",
                    "echo $SAFE_FETCH_ALLOW_PRIVATE_NETWORK",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout.strip()
        except Exception:
            permite = ""
        self.anota(
            "crm",
            "Chatwoot puede llamar al bot (red privada permitida)",
            "ok" if (permite == "true" or not privado) else "mal",
            f"SAFE_FETCH_ALLOW_PRIVATE_NETWORK={permite or 'sin poner'}",
            []
            if (permite == "true" or not privado)
            else [
                "Sin esto del CRM NO vuelve nada: ni las respuestas de Lía ni",
                "las etiquetas. Ponlo en docker/chatwoot/.env y levanta Chatwoot.",
            ],
        )
        errores = ""
        try:
            errores = subprocess.run(
                ["docker", "logs", "--since", "30m", "chatwoot-sidekiq-1"],
                capture_output=True,
                text=True,
                timeout=120,
            ).stderr
        except Exception:
            errores = ""
        rotos = errores.count("Invalid webhook URL")
        self.anota(
            "crm",
            "Chatwoot entregó sus webhooks",
            "ok" if rotos == 0 else "mal",
            f"{rotos} rechazado(s) en la última media hora",
            []
            if rotos == 0
            else ["docker logs chatwoot-sidekiq-1 | grep 'Invalid webhook'"],
        )

        self.anota(
            "crm",
            "el bot firma sus mensajes",
            "ok" if self.s.chatwoot_bot_token else "mal",
            "token del agente bot en .env" if self.s.chatwoot_bot_token else "sin token",
            []
            if self.s.chatwoot_bot_token
            else ["vb chatwoot --conectar y reinicia el bot"],
        )

        # Etiquetas: son la organización entera (etapas, alertas, acciones).
        from app.domain.seguimiento import ACCIONES, ALERTAS, ETAPAS

        esperadas = (
            {e[0] for e in ETAPAS} | {a[0] for a in ALERTAS} | {a[0] for a in ACCIONES}
        )
        try:
            hay = {e["title"] for e in self._cw("/labels")["payload"]}
            faltan = esperadas - hay
            self.anota(
                "crm",
                "etiquetas (etapas, alertas y acciones)",
                "ok" if not faltan else "mal",
                f"{len(esperadas & hay)}/{len(esperadas)}",
                []
                if not faltan
                else [f"faltan: {', '.join(sorted(faltan))}", "vb chatwoot --conectar"],
            )
        except Exception as e:
            self.anota("crm", "etiquetas", "mal", str(e)[:60])

    # ── 4. Credenciales y modelos ──────────────────────────────────────────

    def _la_cuenta_de_whatsapp(self, s) -> None:
        """Si Meta deja escribir desde el número (ver `app/domain/salud_meta.py`)."""
        from app.domain.salud_meta import leer_salud

        if not (s.wa_access_token and s.wa_phone_number_id):
            return
        try:
            r = self._get(
                f"https://graph.facebook.com/v23.0/{s.wa_phone_number_id}",
                params={
                    "fields": "health_status,quality_rating,messaging_limit_tier",
                },
                headers={"Authorization": f"Bearer {s.wa_access_token}"},
            )
            d = r.json()
        except Exception as e:
            self.anota("claves", "Meta deja escribir", "ojo", f"no respondió: {e}")
            return
        if "error" in d:
            msg = d["error"].get("message", "")
            self.anota("claves", "Meta deja escribir", "mal", _sin_secretos(msg))
            return
        salud = leer_salud(d.get("health_status"))
        calidad = d.get("quality_rating", "?")
        tope = d.get("messaging_limit_tier", "?").replace("TIER_", "")
        estado = {"AVAILABLE": "ok", "LIMITED": "ojo"}.get(salud.estado, "mal")
        if calidad not in ("GREEN", "UNKNOWN") and estado == "ok":
            estado = "ojo"
        self.anota(
            "claves",
            "Meta deja escribir (avisos y cobro del saldo)",
            estado,
            f"calidad {calidad} · tope {tope} clientas nuevas al día",
            salud.problemas,
        )

    def credenciales(self) -> None:
        self.titulo("4. CREDENCIALES (nunca se muestran)")
        s = self.s
        self.anota(
            "claves",
            "Meta / WhatsApp",
            "ok"
            if (s.wa_access_token and s.wa_phone_number_id and s.meta_app_secret)
            else "mal",
            "token, número y secreto",
            [] if s.wa_access_token else ["vb token dice cómo renovarlo"],
        )
        self._la_cuenta_de_whatsapp(s)
        self._la_ia(s)
        self._el_esquema_de_la_jugada(s)
        self.anota(
            "claves",
            "LangSmith (auditoría de cada turno)",
            "ok" if (s.langsmith_tracing and s.langsmith_api_key) else "ojo",
            f"proyecto «{s.langsmith_project}»"
            if s.langsmith_tracing
            else "apagado: no se podrá auditar",
        )
        if s.langsmith_tracing and s.langsmith_api_key:
            self._llegan_las_trazas(s)
        self.anota(
            "claves",
            "Groq (notas de voz)",
            "ok" if (s.transcripcion_backend == "groq" and s.groq_api_key) else "ojo",
            s.groq_modelo_audio
            if s.transcripcion_backend == "groq"
            else "apagado: le pide a la clienta que escriba",
        )
        llave = s.google_service_account_json
        buena = False
        if llave and Path(llave).exists():
            try:
                d = json.loads(Path(llave).read_text(encoding="utf-8"))
                buena = d.get("type") == "service_account"
                correo = d.get("client_email", "")
            except Exception:
                correo = "el archivo no es un JSON válido"
        else:
            correo = "no está el archivo"
        self.anota(
            "claves",
            "Google (el ERP)",
            "ok" if buena else "mal",
            correo if buena else f"no sirve: {correo}",
            [] if buena else ["Mira docs/sistema/08-erp.md"],
        )
        # Que ninguna clave se haya colado al historial de Git.
        try:
            rastreado = subprocess.run(
                ["git", "ls-files", ".env", "credenciales/*.json"],
                cwd=RAIZ,
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()
        except Exception:
            rastreado = ""
        self.anota(
            "claves",
            "ningún secreto dentro de Git",
            "ok" if not rastreado else "mal",
            "" if not rastreado else rastreado.replace("\n", ", "),
            [] if not rastreado else ["git rm --cached <archivo> y rota esa clave"],
        )

    # ── 5. Los datos ───────────────────────────────────────────────────────

    def datos(self) -> None:
        self.titulo("5. LOS DATOS")
        base = Path(self.s.sqlite_path)
        if not base.exists():
            self.anota("datos", "la base existe", "mal", str(base))
            return
        cx = sqlite3.connect(str(base))
        entero = cx.execute("PRAGMA integrity_check").fetchone()[0]
        self.anota(
            "datos",
            "la base está sana",
            "ok" if entero == "ok" else "mal",
            f"{base.name} · {base.stat().st_size // 1024} KB",
            [] if entero == "ok" else [entero[:100]],
        )
        cuenta = {
            t: cx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("orders", "conversations", "messages", "outbox")
            if cx.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone()
        }
        self.anota(
            "datos",
            "qué hay dentro",
            "ok",
            " · ".join(f"{k}={v}" for k, v in cuenta.items()),
        )
        cx.close()

        # En el servidor, las copias quedan en el volumen (RESPALDOS_DIR); en
        # el PC, lo que cuenta es la copia que se trae del servidor cada noche
        # (scripts/traer-respaldos.cmd). Desde el 25/09 el PC ya no atiende.
        if EN_EL_SERVIDOR:
            copias = Path(os.environ.get("RESPALDOS_DIR", "/app/estado/respaldos"))
        else:
            copias = (
                Path.home() / "Documents" / "Respaldos" / "VentaBot" / "servidor" / "bot"
            )
        ultimas = sorted(copias.glob("ventabot-*.db")) if copias.exists() else []
        fresca = bool(ultimas) and (
            datetime.fromtimestamp(ultimas[-1].stat().st_mtime).astimezone()
            > datetime.now().astimezone() - timedelta(days=2)
        )
        self.anota(
            "datos",
            "hay un respaldo reciente",
            "ok" if fresca else "ojo",
            ultimas[-1].name if ultimas else "ninguno",
            [] if fresca else ["vb respaldo"],
        )
        # El catálogo y los fletes: si faltan, el bot cotiza mal.
        for nombre, ruta in (
            ("catálogo", RAIZ / "data" / "catalogo.csv"),
            ("fletes", RAIZ / "data" / "fletes.csv"),
        ):
            filas = (
                len(ruta.read_text(encoding="utf-8").splitlines()) - 1
                if ruta.exists()
                else 0
            )
            self.anota("datos", nombre, "ok" if filas > 0 else "mal", f"{filas} fila(s)")

    # ── 6. El ERP ──────────────────────────────────────────────────────────

    def erp(self) -> None:
        self.titulo("6. EL ERP (HUELLAS_ERP_v1)")
        if not (self.s.sheets_spreadsheet_id and self.s.google_service_account_json):
            self.anota(
                "erp",
                "conectado",
                "ojo",
                "apagado: el bot funciona igual",
                ["Mira docs/sistema/08-erp.md"],
            )
            return
        try:
            from app.adapters.erp.sheets import SheetsDeGoogle

            hoja = SheetsDeGoogle(
                self.s.sheets_spreadsheet_id,
                Path(self.s.google_service_account_json),
            )
            nombre, hojas = hoja.titulo()
            self.anota("erp", "el ERP abre", "ok", f"«{nombre}» · {len(hojas)} hoja(s)")
            faltan = {"Ventas", "Pagos", "Produccion"} - set(hojas)
            self.anota(
                "erp",
                "están las hojas que llena el bot",
                "ok" if not faltan else "mal",
                "Ventas · Pagos · Produccion",
                [] if not faltan else [f"faltan: {', '.join(sorted(faltan))}"],
            )
            # La primera pestaña del ERP dice dónde está el bot y si está vivo.
            # La escribe el bot al arrancar: si no está, algo le impide escribir.
            from app.infra.centro_de_mando import NOMBRE_DE_LA_HOJA

            esta = NOMBRE_DE_LA_HOJA in hojas
            self.anota(
                "erp",
                "la hoja CENTRO DE MANDO dice dónde está el bot",
                "ok" if esta else "ojo",
                "primera pestaña del ERP" if esta else "todavía no está",
                []
                if esta
                else [
                    "La escribe el bot al arrancar: si acaba de encender, espera "
                    "un minuto; si no, mira el registro"
                ],
            )
        except Exception as e:
            self.anota("erp", "el ERP abre", "mal", str(e)[:80], ["vb erp (lo explica)"])

    # ── 7. El código ───────────────────────────────────────────────────────

    def codigo(self) -> None:
        self.titulo("7. EL CÓDIGO")
        if self.rapido:
            self.anota(
                "codigo", "tests, estilo y arquitectura", "ojo", "omitido (--rapido)"
            )
            return
        if EN_EL_SERVIDOR:
            # Las pruebas no van en la imagen: se corren en el PC antes de
            # subir (SUBIR-A-GITHUB.cmd no sube nada si alguna falla).
            self.anota(
                "codigo",
                "tests, estilo y arquitectura",
                "ok",
                "se revisan antes de subir",
            )
            return
        pruebas = (
            ("los tests pasan", [sys.executable, "-m", "pytest", "-q", "--no-header"]),
            ("el estilo está limpio", [sys.executable, "-m", "ruff", "check", "."]),
            ("la arquitectura se respeta", ["lint-imports"]),
        )
        for nombre, cmd in pruebas:
            inicio = time.time()
            try:
                p = subprocess.run(
                    cmd, cwd=RAIZ, capture_output=True, text=True, timeout=600
                )
            except Exception as e:
                self.anota("codigo", nombre, "mal", str(e)[:70])
                continue
            salida = (p.stdout or "") + (p.stderr or "")
            resumen = ""
            if m := re.search(r"(\d+) passed", salida):
                resumen = f"{m.group(1)} pruebas"
            if m := re.search(r"(\d+) failed", salida):
                resumen = f"{m.group(1)} FALLAN"
            self.anota(
                "codigo",
                nombre,
                "ok" if p.returncode == 0 else "mal",
                f"{resumen} · {time.time() - inicio:.0f}s".strip(" ·"),
                [] if p.returncode == 0 else [salida.strip().splitlines()[-1][:100]],
            )

    # ── 8. Residuos ────────────────────────────────────────────────────────

    def limpieza(self) -> None:
        self.titulo("8. LIMPIEZA")
        registros = (
            sorted((RAIZ / "logs").glob("*.log")) if (RAIZ / "logs").exists() else []
        )
        pesados = [f for f in registros if f.stat().st_size > 20_000_000]
        self.anota(
            "limpieza",
            "los registros no se desbordan",
            "ok" if not pesados else "ojo",
            f"{len(registros)} archivo(s)",
            [] if not pesados else [f"{f.name} pesa mucho" for f in pesados],
        )
        errores = self._errores_de_la_ultima_hora()
        self.anota(
            "limpieza",
            "sin errores recientes en el servidor",
            "ok" if errores == 0 else "ojo",
            f"{errores} en la última hora",
            [] if errores == 0 else ["Mira el final de logs/servidor.log"],
        )

    @staticmethod
    def _errores_de_la_ultima_hora() -> int:
        """Cuántos errores hay en el registro DESDE HACE UNA HORA.

        Contar los de todo el archivo hacía que un error de anoche siguiera
        marcando el diagnóstico en rojo hoy, cuando ya estaba arreglado. Lo que
        importa saber al encender es si algo está fallando AHORA.
        """
        archivo = RAIZ / "logs" / "servidor.log"
        if not archivo.exists():
            return 0
        from datetime import datetime, timedelta

        ahora = datetime.now().astimezone()
        limite = (ahora - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        # El registro pone «2026-09-20 03:07:41» al principio de cada línea.
        # Comparar como texto funciona porque el formato va de mayor a menor.
        #
        # Una línea SIN fecha es vieja por definición: desde que el registro
        # lleva fecha (20/09), todas las nuevas la traen. Antes se contaban por
        # prudencia y el diagnóstico seguía marcando en ámbar errores de
        # anoche que ya estaban arreglados.
        cola = archivo.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
        errores = 0
        for linea in cola:
            marca = linea[:19]
            if not (len(marca) == 19 and marca[4] == "-" and marca[7] == "-"):
                continue  # sin fecha: de antes de que el registro la llevara
            if marca < limite:
                continue
            if " ERROR " in linea or "Traceback" in linea:
                errores += 1
        return errores

    # -- informe ------------------------------------------------------------

    def correr(self) -> int:
        print(f"\n{C}{'=' * 74}")
        print("  DIAGNÓSTICO DE VENTABOT · todo, de punta a punta")
        print(f"{'=' * 74}{RST}")
        for paso in (
            self.servidor,
            self.tunel,
            self.chatwoot,
            self.credenciales,
            self.datos,
            self.erp,
            self.codigo,
            self.limpieza,
        ):
            try:
                paso()
            except Exception as e:
                self.anota(
                    paso.__name__,
                    f"la revisión «{paso.__name__}» se cayó",
                    "mal",
                    str(e)[:80],
                )
        return self.informe()

    def informe(self) -> int:
        malos = [x for x in self.r if x.estado == "mal"]
        ojos = [x for x in self.r if x.estado == "ojo"]
        bien = len(self.r) - len(malos) - len(ojos)
        print(f"\n{C}{'=' * 74}{RST}")
        if malos:
            print(
                f"  {R}{len(malos)} ROTO(S){RST}   {bien} bien   "
                f"{len(ojos)} por mirar   (de {len(self.r)})"
            )
            print(f"\n  {B}Lo que hay que arreglar:{RST}")
            for x in malos:
                print(f"    {MAL} [{x.grupo}] {x.nombre} — {x.detalle}")
                for a in x.arreglo:
                    print(f"        {A}→{RST} {a}")
            veredicto = "ROTO"
        elif ojos:
            print(
                f"  {V}TODO EN VERDE{RST}   {bien} bien   "
                f"{A}{len(ojos)} por mirar{RST}   (de {len(self.r)})"
            )
            for x in ojos:
                print(f"    {OJO} [{x.grupo}] {x.nombre} — {x.detalle}")
            veredicto = "LISTO (con avisos)"
        else:
            print(f"  {V}{B}TODO EN VERDE{RST}   las {len(self.r)} revisiones pasaron")
            veredicto = "LISTO"
        print(f"{C}{'=' * 74}{RST}\n")

        REGISTRO.parent.mkdir(exist_ok=True)
        with REGISTRO.open("a", encoding="utf-8") as f:
            f.write(
                f"{datetime.now().astimezone():%Y-%m-%d %H:%M}  {veredicto}  "
                f"{bien} ok / {len(malos)} mal / {len(ojos)} aviso"
                + (
                    "  ·  " + "; ".join(f"{x.grupo}:{x.nombre}" for x in malos)
                    if malos
                    else ""
                )
                + "\n"
            )
        self.veredicto = veredicto
        return 1 if malos else 0


def _ventanita(d: Diagnostico) -> None:
    """Una ventana pequeña con el resultado: para cuando corre sola al encender."""
    malos = [x for x in d.r if x.estado == "mal"]
    cuerpo = d.veredicto + "\n\n"
    cuerpo += (
        "\n".join(f"- {x.nombre}: {x.detalle}" for x in malos)
        if malos
        else f"Las {len(d.r)} revisiones pasaron.\nEl bot esta listo para atender."
    )
    icono = "Error" if malos else "Information"
    guion = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        f"[System.Windows.Forms.MessageBox]::Show('{cuerpo[:700].replace(chr(39), '')}',"
        f"'VentaBot - diagnostico','OK','{icono}')"
    )
    # Suelta: la ventanita espera un clic, y quien encendio el bot no tiene
    # por que quedarse mirandola para que siga el arranque.
    with __import__("contextlib").suppress(Exception):
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", guion],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="Revisa VentaBot de punta a punta")
    ap.add_argument("--rapido", action="store_true", help="sin tests ni lint")
    ap.add_argument("--ventana", action="store_true", help="avisa con una ventanita")
    ap.add_argument("--json", action="store_true", help="salida para máquinas")
    args = ap.parse_args()

    d = Diagnostico(rapido=args.rapido)
    codigo = d.correr()
    if args.json:
        print(json.dumps([x.__dict__ for x in d.r], ensure_ascii=False, indent=2))
    if args.ventana:
        _ventanita(d)
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
