#!/usr/bin/env python3
"""PREFLIGHT DE LA FASE 0 — te dice exactamente qué falta y cómo arreglarlo.

    python scripts/preflight.py            # todo
    python scripts/preflight.py --local    # omite lo que depende de terceros
    python scripts/preflight.py --json     # salida para CI

Cada comprobación devuelve uno de tres estados:

    OK          hecho y verificado
    FALTA       lo puedes arreglar tú ahora; te digo el comando exacto
    MANUAL      depende de un tercero (Meta, Bold, tu GPU); te digo qué hacer

La Fase 0 está cerrada cuando no queda ningún FALTA y los MANUAL están hechos.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# Las herramientas (ruff, mypy, lint-imports) viven junto al Python del entorno
# del proyecto: se buscan ahí primero, aunque el entorno no esté «activado».
# Sin esto, el preflight decía «ruff no encontrado» con ruff instalado.
os.environ["PATH"] = (
    str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
)
sys.path.insert(0, str(RAIZ))

from app.infra.consola import preparar_salida

# UTF-8 y color solo si hay terminal: sin esto, redirigir la salida a un
# archivo revienta en Windows al imprimir un ✔ (cp1252 no lo soporta).
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
OK, FALTA, MANUAL = "OK", "FALTA", "MANUAL"
ICONO = {OK: f"{V}✔{RST}", FALTA: f"{R}✘{RST}", MANUAL: f"{A}○{RST}"}


@dataclass
class Check:
    grupo: str
    nombre: str
    estado: str
    detalle: str = ""
    arreglo: list[str] = field(default_factory=list)


resultados: list[Check] = []


def add(grupo, nombre, estado, detalle="", arreglo=None):
    resultados.append(Check(grupo, nombre, estado, detalle, arreglo or []))


#: Windows y Unix no comparten ni comandos ni separadores. Las ayudas que
#: imprime el preflight deben poder pegarse TAL CUAL en la máquina de quien lo
#: corre: una ayuda que no se puede copiar no es una ayuda. Antes se sugería
#: `make setup` y `source .venv/bin/activate` a un usuario de Windows.
ES_WINDOWS = os.name == "nt"


def _cmd(windows: str, unix: str | None = None) -> str:
    """El comando correcto para este sistema operativo."""
    return windows if ES_WINDOWS else (unix if unix is not None else windows)


def corre(cmd: list[str], timeout=60) -> tuple[int, str]:
    try:
        # UTF-8 explícito: en Windows la salida de pytest trae tildes y emojis, y
        # con la codificación por defecto (cp1252) el preflight se caía entero.
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=RAIZ,
        )
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except FileNotFoundError:
        return 127, "comando no encontrado"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


# === 1. Entorno de Python ==================================================


def check_python():
    v = sys.version_info
    if v >= (3, 11):
        add("Entorno", f"Python {v.major}.{v.minor}.{v.micro}", OK)
    else:
        add(
            "Entorno",
            "Python >= 3.11",
            FALTA,
            f"tienes {v.major}.{v.minor}",
            ["Instala Python 3.11 o superior"],
        )

    # Hay TRES formas legítimas de tener un entorno aislado, y detectarlas mal
    # produce un falso positivo muy molesto:
    #   · venv / virtualenv -> sys.prefix != sys.base_prefix, o VIRTUAL_ENV
    #   · conda / mamba     -> CONDA_DEFAULT_ENV. OJO: los entornos de conda son
    #                          instalaciones COMPLETAS, así que sys.prefix ==
    #                          sys.base_prefix y la comprobación clásica falla.
    #   · el `base` de conda -> NO cuenta: ahí viven tus otros proyectos.
    venv = sys.prefix != sys.base_prefix or bool(os.environ.get("VIRTUAL_ENV"))
    conda_env = os.environ.get("CONDA_DEFAULT_ENV", "")

    if conda_env and conda_env != "base":
        add("Entorno", "Entorno aislado activo", OK, f"conda: {conda_env}")
    elif venv:
        add("Entorno", "Entorno aislado activo", OK, sys.prefix)
    elif conda_env == "base":
        add(
            "Entorno",
            "Entorno aislado activo",
            FALTA,
            "estás en el `base` de conda, donde viven tus otros proyectos",
            [
                ".venv\\Scripts\\activate.bat",
                "si aún no existe: " + _cmd("vb setup", "make setup"),
            ],
        )
    else:
        add(
            "Entorno",
            "Entorno aislado activo",
            FALTA,
            "estás usando el Python del sistema",
            [
                _cmd("vb setup", "make setup"),
                _cmd(".venv\\Scripts\\activate.bat", "source .venv/bin/activate"),
            ],
        )


def check_deps():
    obligatorias = {
        "langgraph": "orquestador",
        # Este submódulo viene en un paquete APARTE (langgraph-checkpoint-sqlite).
        # Faltaba en requirements.txt y el preflight no lo miraba: 11 tests
        # reventaban con un ModuleNotFoundError que no decía qué instalar.
        "langgraph.checkpoint.sqlite": "checkpoints en disco",
        "pydantic": "validación",
        "pydantic_settings": "configuración",
        "yaml": "reglas de negocio",
        "httpx": "cliente HTTP",
        "fastapi": "webhooks (Fase 1)",
        "ollama": "LLM local (Fase 2)",
        # Las dos que dibujan la previsualización. Faltaban en esta lista, y el
        # preflight decía «Dependencias de runtime ✔» con Pillow sin instalar:
        # 11 tests en rojo y, en producción, un bot que vende bien y solo falla
        # al enseñarle a la clienta cómo le va a quedar el anillo — el momento
        # exacto en que se decide la compra.
        "PIL": "dibujar la previsualización (Fase 6)",
        "numpy": "teñir las piedras de la previsualización (Fase 6)",
        # Sin esta, el Excel de ventas deja de actualizarse sin que nadie lo note.
        "openpyxl": "Excel de ventas (ADR 0015)",
    }
    #: Cuando el módulo no se llama igual que el paquete de pip, decirlo.
    paquete_pip = {
        "yaml": "pyyaml",
        "pydantic_settings": "pydantic-settings",
        "langgraph.checkpoint.sqlite": "langgraph-checkpoint-sqlite",
        "PIL": "pillow",
    }
    faltan = []
    for mod, para in obligatorias.items():
        try:
            __import__(mod)
        except ImportError:
            faltan.append(f"{paquete_pip.get(mod, mod)} ({para})")
    if faltan:
        add(
            "Entorno",
            "Dependencias de runtime",
            FALTA,
            ", ".join(faltan),
            ["pip install -r requirements.txt"],
        )
    else:
        add("Entorno", f"Dependencias de runtime ({len(obligatorias)})", OK)

    herramientas = {
        "ruff": "linter",
        "mypy": "tipos",
        "lint-imports": "arquitectura",
        "pre-commit": "hooks",
    }
    faltan_h = [f"{h} ({p})" for h, p in herramientas.items() if not shutil.which(h)]
    if faltan_h:
        add(
            "Entorno",
            "Herramientas de calidad",
            FALTA,
            ", ".join(faltan_h),
            ["pip install -r requirements-dev.txt"],
        )
    else:
        add(
            "Entorno",
            "Herramientas de calidad (ruff, mypy, import-linter, pre-commit)",
            OK,
        )


# === 2. Repositorio ========================================================


def check_git():
    # Antes se daba por hecho que git estaba instalado. Si no lo estaba, TODAS
    # las comprobaciones de git fallaban en silencio y salían en verde: "0
    # commits" y "árbol limpio". Un preflight que miente es peor que no tenerlo.
    if not shutil.which("git"):
        add(
            "Repo",
            "Git instalado",
            MANUAL,
            "no está en el PATH",
            [
                "Descárgalo de https://git-scm.com/download/win"
                if ES_WINDOWS
                else "Instálalo con el gestor de paquetes de tu sistema",
                "Cierra y vuelve a abrir la terminal después de instalarlo",
                "No bloquea la Fase 0, pero sin él no puedes deshacer un cambio",
            ],
        )
        return

    if not (RAIZ / ".git").exists():
        add(
            "Repo",
            "Repositorio Git",
            FALTA,
            "no hay carpeta .git",
            ["git init -b main", "git add -A", 'git commit -m "estado inicial"'],
        )
        return

    cod, out = corre(["git", "rev-list", "--count", "HEAD"])
    if cod != 0:
        primera = out.splitlines()[0][:90] if out else "sin mensaje"
        add(
            "Repo",
            "Repositorio Git",
            FALTA,
            f"git falló: {primera}",
            [
                "Si dice 'dubious ownership' o 'propiedad dudosa', corre:",
                f'  git config --global --add safe.directory "{RAIZ}"',
            ],
        )
        return
    add("Repo", "Repositorio Git", OK, f"{out.strip()} commit(s)")

    cod, out = corre(["git", "status", "--porcelain"])
    if cod != 0:
        add("Repo", "Árbol limpio", FALTA, "no se pudo consultar el estado", [])
    elif out:
        add(
            "Repo",
            "Árbol limpio",
            FALTA,
            f"{len(out.splitlines())} archivo(s) sin guardar en el historial",
            ['git add -A && git commit -m "avance"'],
        )
    else:
        add("Repo", "Árbol limpio", OK)


def check_gitignore():
    gi = RAIZ / ".gitignore"
    if not gi.exists():
        add("Repo", ".gitignore", FALTA, "no existe", ["Crea .gitignore con .env dentro"])
        return
    txt = gi.read_text(encoding="utf-8")
    # `data/fotos` es crítico por la misma razón que `.env`: ahí caen los
    # comprobantes de transferencia de las clientas, con nombre, cuenta y
    # monto. Un commit los mete en el historial para siempre.
    criticos = [".env", "credentials", "__pycache__", ".venv", "data/fotos"]
    faltan = [c for c in criticos if c not in txt]
    if faltan:
        add(
            "Repo",
            ".gitignore protege secretos",
            FALTA,
            f"falta ignorar: {faltan}",
            [f"echo '{c}' >> .gitignore" for c in faltan],
        )
    else:
        add("Repo", ".gitignore protege secretos", OK)

    # El error más caro: que .env ya esté rastreado por Git.
    cod, _ = corre(["git", "ls-files", "--error-unmatch", ".env"])
    if cod == 0:
        add(
            "Repo",
            ".env NO está en Git",
            FALTA,
            "¡el .env está rastreado!",
            [
                "git rm --cached .env",
                "git commit -m 'saca .env del repo'",
                "Y ROTA todos los tokens que ya subiste.",
            ],
        )
    else:
        add("Repo", ".env NO está en Git", OK)

    # Las fotos de las clientas, igual: si ya entraron, sacarlas del índice.
    cod, salida = corre(["git", "ls-files", "data/fotos"])
    rastreadas = [ln for ln in salida.splitlines() if ln.strip()]
    if cod == 0 and rastreadas:
        add(
            "Repo",
            "Fotos de clientas fuera de Git",
            FALTA,
            f"{len(rastreadas)} foto(s) rastreada(s) por Git",
            [
                "git rm -r --cached data/fotos",
                "git commit -m 'las fotos de las clientas no van al repositorio'",
                "Son datos personales de terceros: comprobantes con cuenta y monto.",
            ],
        )
    else:
        add("Repo", "Fotos de clientas fuera de Git", OK)


def check_pre_commit():
    if (RAIZ / ".git" / "hooks" / "pre-commit").exists():
        add("Repo", "Hooks de pre-commit instalados", OK)
    else:
        add(
            "Repo",
            "Hooks de pre-commit instalados",
            FALTA,
            "no están activos",
            ["pre-commit install"],
        )


# === 3. Configuración y datos ==============================================


def check_env():
    if not (RAIZ / ".env").exists():
        add(
            "Config",
            "Archivo .env",
            FALTA,
            "no existe",
            [
                _cmd("vb init-env", "make init-env")
                + "   ← lo crea y genera el token de Meta por ti"
            ],
        )
        return
    add("Config", "Archivo .env", OK)


def check_reglas():
    try:
        from app.infra.reglas import cargar_reglas, marcadores_por_definir

        ruta = RAIZ / "config" / "reglas.yaml"
        cargar_reglas(ruta)
        pendientes = marcadores_por_definir(ruta)
        add(
            "Config",
            "config/reglas.yaml válido",
            OK,
            f"{len(pendientes)} regla(s) con valor supuesto [POR DEFINIR]",
        )
    except Exception as exc:
        add(
            "Config",
            "config/reglas.yaml válido",
            FALTA,
            str(exc)[:160],
            ["Revisa config/reglas.yaml contra app/infra/reglas.py"],
        )


def check_datos():
    try:
        from app.adapters.repositories.csv_files import CsvFletes, cargar_catalogo_csv

        ps = cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv")
        activos = sum(p.activo for p in ps)
        add("Config", "data/catalogo.csv", OK, f"{len(ps)} productos, {activos} activos")
        fl = CsvFletes(RAIZ / "data" / "fletes.csv", 15000, 3)
        add("Config", "data/fletes.csv", OK, f"{len(fl.ciudades())} ciudades")
    except Exception as exc:
        add(
            "Config",
            "Datos semilla (catálogo y fletes)",
            FALTA,
            str(exc)[:160],
            ["Revisa data/catalogo.csv y data/fletes.csv"],
        )


def check_url_publica():
    """Sin esto el bot contesta perfecto y no manda NI UNA foto.

    Es el fallo más silencioso que ha tenido el proyecto: el webhook entra,
    las respuestas salen, todo se ve bien en el log — y las fotos, los videos
    y el muestrario se quedan dentro, con un WARNING por mensaje que nadie
    lee porque el bot «funciona».
    """
    try:
        from app.infra.settings import get_settings

        s = get_settings()
        if s.url_publica.startswith("https://"):
            add("Config", "URL pública (fotos y videos)", OK, s.url_publica)
        elif s.url_publica:
            add(
                "Config",
                "URL pública (fotos y videos)",
                FALTA,
                f"{s.url_publica} no es https",
                ["Meta solo baja de https. Usa la URL de ngrok."],
            )
        else:
            add(
                "Config",
                "URL pública (fotos y videos)",
                FALTA,
                "sin definir: el bot NO manda fotos ni videos",
                [
                    "ngrok http 8000",
                    "y pon PUBLIC_URL=https://... en tu .env",
                    "(o corre  vb panel , que la detecta sola)",
                ],
            )
    except Exception as exc:
        add("Config", "URL pública (fotos y videos)", FALTA, str(exc)[:160], [])


def check_cuentas():
    """Los números de las cuentas de pago. Sin ellos no entra plata.

    Es MANUAL a propósito: no hay comando que se los invente. Mientras estén
    sin poner, el bot le dice a la clienta que los confirma y se los manda —
    honesto, pero es una venta que se enfría cada vez.
    """
    try:
        from app.domain.faq import cuentas_sin_definir

        faltan = cuentas_sin_definir()
        if not faltan:
            add("Config", "Cuentas de pago", OK, "todas con datos")
            return
        add(
            "Config",
            "Cuentas de pago",
            MANUAL,
            f"sin datos: {', '.join(faltan)}",
            [
                "Abre app/domain/faq.py y busca CUENTAS",
                "Pon el número y el titular de cada cuenta de Lía",
                "El titular va SIEMPRE: es lo que la clienta compara antes de enviar",
            ],
        )
    except Exception as exc:
        add("Config", "Cuentas de pago", FALTA, str(exc)[:160], [])


def check_settings():
    try:
        from app.infra.settings import get_settings

        s = get_settings()
        add(
            "Config",
            "Settings cargan",
            OK,
            f"repo={s.repository_backend} llm={s.llm_backend} pago={s.payment_backend}",
        )
        # DÓNDE VIVEN LOS PEDIDOS. Con `memory` viven en RAM, y al parar el
        # servidor se pierden todos: los pedidos, las clientas y el hilo de
        # cada conversación. Para la demo está perfecto; con el canal en
        # WhatsApp es pérdida de datos silenciosa, porque el bot vende bien y
        # solo falla al reiniciar — contestándole «todavía no me aparece
        # ningún pedido tuyo» a quien acaba de abonar $60.000.
        #
        # Estaba así en un .env de verdad, y ningún comando lo decía.
        if s.repository_backend == "memory":
            vendiendo = s.channel_backend == "whatsapp"
            add(
                "Config",
                "Dónde viven los pedidos",
                FALTA if vendiendo else MANUAL,
                "en RAM: se pierden TODOS al parar el servidor"
                + (" — y el canal es WhatsApp" if vendiendo else ""),
                [
                    "Pon REPOSITORY_BACKEND=sqlite en tu .env",
                    "`memory` solo para la demo y los tests",
                ],
            )
        else:
            add(
                "Config",
                "Dónde viven los pedidos",
                OK,
                f"{s.repository_backend} · {s.sqlite_path.name}",
            )

        # EL MODELO DE RESCATE. No se llama a la API aquí —costaría dinero cada
        # vez que corres preflight—, solo se mira que la configuración cuadre.
        # El fallo que se caza es el más tonto y el más probable: un modelo
        # claude-* puesto y la clave vacía. Sin esto, el rescate no funcionaba
        # y el único aviso salía enterrado en el log del servidor.
        if s.llm_backend == "claude":
            add(
                "Config",
                "Modelo básico (1.ª capa)",
                OK if s.anthropic_api_key else FALTA,
                s.llm_basico_model
                if s.anthropic_api_key
                else f"{s.llm_basico_model} sin clave: se usará el modelo local",
                [] if s.anthropic_api_key else ["Pon ANTHROPIC_API_KEY en tu .env"],
            )
        if not s.llm_fuerte_model:
            add(
                "Config",
                "Modelo de rescate",
                MANUAL,
                "apagado: los turnos que el modelo local no entienda se quedan "
                "en «no te entendí»",
                ["Opcional. Ver LLM_FUERTE_MODEL en .env.example"],
            )
        elif s.llm_fuerte_model.startswith("claude") and not s.anthropic_api_key:
            add(
                "Config",
                "Modelo de rescate",
                FALTA,
                f"{s.llm_fuerte_model} sin clave: no se va a usar nunca",
                ["Pon ANTHROPIC_API_KEY en tu .env"],
            )
        else:
            add("Config", "Modelo de rescate", OK, s.llm_fuerte_model)
    except Exception as exc:
        add("Config", "Settings cargan", FALTA, str(exc)[:160], ["Revisa tu .env"])


# === 4. Calidad ============================================================


def check_tests():
    cod, out = corre(
        [sys.executable, "-m", "pytest", "-q", "-m", "not integracion", "--no-header"],
        timeout=300,
    )
    lineas = [ln for ln in out.strip().splitlines() if ln.strip()]
    if cod == 0:
        add("Calidad", "Tests", OK, lineas[-1][:110] if lineas else "")
        return

    # Antes se mostraba UNA sola línea truncada a 110 caracteres. Con eso es
    # imposible saber qué falló, y hacen falta varias rondas de preguntas.
    # Ahora se muestran los nombres de los tests rotos y cómo ver el detalle.
    rotos = [
        ln
        for ln in lineas
        if ln.startswith(("FAILED", "ERROR")) or " failed" in ln or " error" in ln
    ][:6]
    add(
        "Calidad",
        "Tests",
        FALTA,
        lineas[-1][:110] if lineas else "pytest no devolvió salida",
        [
            *[f"· {r[:100]}" for r in rotos],
            "Para ver el detalle completo y mandármelo:",
            _cmd(
                "python -m pytest -v --tb=long > diagnostico.txt 2>&1",
                "python3 -m pytest -v --tb=long > diagnostico.txt 2>&1",
            ),
        ],
    )


def check_lint():
    cod, out = corre(["ruff", "check", "app", "tests", "scripts"])
    add(
        "Calidad",
        "Lint (ruff)",
        OK if cod == 0 else FALTA,
        "" if cod == 0 else out.strip().splitlines()[-1][:110],
        [] if cod == 0 else [_cmd("vb fmt", "make fmt")],
    )


def check_arquitectura():
    cod, _ = corre(["lint-imports"])
    if cod == 127:
        add(
            "Calidad",
            "Arquitectura hexagonal",
            FALTA,
            "import-linter no instalado",
            ["pip install import-linter"],
        )
        return
    add(
        "Calidad",
        "Arquitectura hexagonal (import-linter)",
        OK if cod == 0 else FALTA,
        "" if cod == 0 else "el dominio importa una capa externa",
        [] if cod == 0 else ["lint-imports  # mira qué contrato se rompió"],
    )


# === 5. Servicios externos =================================================


def check_docker():
    if not shutil.which("docker"):
        add(
            "Servicios",
            "Docker instalado",
            MANUAL,
            "no está",
            ["Instala Docker Desktop: https://docs.docker.com/get-docker/"],
        )
        return
    cod, _ = corre(["docker", "info"], timeout=20)
    if cod != 0:
        add(
            "Servicios",
            "Docker corriendo",
            MANUAL,
            "el demonio no responde",
            ["Abre Docker Desktop y espera a que arranque"],
        )
        return
    cod, out = corre(["docker", "compose", "config", "--quiet"], timeout=30)
    add(
        "Servicios",
        "docker-compose.yml válido",
        OK if cod == 0 else FALTA,
        "" if cod == 0 else out[:110],
        [] if cod == 0 else ["docker compose config"],
    )

    # El bot usa SQLite: ya no hay Postgres ni Redis que revisar. Lo que importa
    # en Docker es que la imagen de producción no se lleve secretos adentro.
    ignorados = (RAIZ / ".dockerignore").read_text(encoding="utf-8").split()
    faltan = [x for x in (".env", "data/ventabot.db", ".venv/") if x not in ignorados]
    add(
        "Servicios",
        "La imagen no se lleva secretos",
        OK if not faltan else FALTA,
        "" if not faltan else "falta en .dockerignore: " + ", ".join(faltan),
        [] if not faltan else ["agrega esas rutas a .dockerignore"],
    )


def check_ollama():
    from app.infra.settings import get_settings

    if get_settings().llm_backend != "ollama":
        # VentaBot trabaja con modelos en línea: Ollama es del equipo, no del bot.
        add("Servicios", "Ollama", OK, "no se usa (LLM_BACKEND en línea)")
        return
    try:
        import httpx

        from app.infra.settings import get_settings

        s = get_settings()
        r = httpx.get(f"{s.ollama_host}/api/tags", timeout=5)
        modelos = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        add(
            "Servicios",
            "Ollama responde",
            MANUAL,
            "no responde",
            ["OLLAMA_CONTEXT_LENGTH=32000 OLLAMA_FLASH_ATTENTION=1 ollama serve"],
        )
        return

    from app.infra.settings import get_settings

    s = get_settings()
    add("Servicios", "Ollama responde", OK, f"{len(modelos)} modelo(s)")
    base = s.ollama_model.split(":")[0]
    if any(m.split(":")[0] == base for m in modelos):
        add("Servicios", f"Modelo {s.ollama_model}", OK)
    else:
        add(
            "Servicios",
            f"Modelo {s.ollama_model}",
            MANUAL,
            "no descargado",
            [f"ollama pull {s.ollama_model}"],
        )

    # Los OJOS. Van aparte porque son un modelo aparte, y porque el bot
    # funciona sin ellos: sin visión, una foto se reconoce como foto, se
    # marca para que la mire una persona, y la conversación sigue.
    if not s.ollama_vision_model:
        add(
            "Servicios",
            "Lector de imágenes",
            MANUAL,
            "apagado",
            [
                "Sin él, las fotos (talla, comprobante, colores) las revisa una persona.",
                "Para encenderlo: ollama pull qwen3-vl:8b",
            ],
        )
        return
    vision = s.ollama_vision_model.split(":")[0]
    if any(m.split(":")[0] == vision for m in modelos):
        add("Servicios", f"Ojos {s.ollama_vision_model}", OK)
    else:
        add(
            "Servicios",
            f"Ojos {s.ollama_vision_model}",
            MANUAL,
            "no descargado",
            [
                f"ollama pull {s.ollama_vision_model}",
                "Mientras tanto las fotos se marcan para revisión humana.",
            ],
        )


def check_asesora_y_ventas():
    """Quién conversa (ADR 0014) y si el Excel de ventas está al día (ADR 0015)."""
    from datetime import datetime

    from app.infra.settings import get_settings

    s = get_settings()
    if (
        s.conversacion_motor == "asesora"
        and s.llm_backend == "claude"
        and s.anthropic_api_key
    ):
        add(
            "Servicios",
            "Conversa la asesora",
            OK,
            f"{s.llm_basico_model}; si la API falla contesta el gestor por etiquetas",
        )
    elif s.conversacion_motor == "asesora":
        add(
            "Servicios",
            "Conversa la asesora",
            MANUAL,
            "sin Claude configurado: contesta el gestor por etiquetas",
            [
                "LLM_BACKEND=claude y ANTHROPIC_API_KEY en el .env",
                "Antes de tocar el prompt, mide: vb repasar",
            ],
        )
    else:
        add(
            "Servicios",
            "Conversa la asesora",
            MANUAL,
            "CONVERSACION_MOTOR=pipeline (el gestor por etiquetas)",
            ["CONVERSACION_MOTOR=asesora en el .env"],
        )

    if s.ventas_cada_s <= 0:
        add(
            "Servicios",
            "Excel de ventas",
            MANUAL,
            "apagado",
            ["VENTAS_CADA_S=120 en el .env"],
        )
    elif s.ventas_excel.is_file():
        cuando = datetime.fromtimestamp(s.ventas_excel.stat().st_mtime).astimezone()
        add(
            "Servicios",
            "Excel de ventas",
            OK,
            f"{s.ventas_excel} ({cuando:%Y-%m-%d %H:%M})",
        )
    else:
        add(
            "Servicios",
            "Excel de ventas",
            MANUAL,
            "todavía no existe",
            ["vb ventas   (o arranca el servidor: se crea solo)"],
        )


def check_credenciales():
    from app.infra.settings import get_settings

    s = get_settings()
    grupos = {
        "Meta / WhatsApp": {
            "WA_PHONE_NUMBER_ID": s.wa_phone_number_id,
            "WA_ACCESS_TOKEN": s.wa_access_token,
            "META_APP_SECRET": s.meta_app_secret,
            "META_VERIFY_TOKEN": s.meta_verify_token,
        },
    }
    ayuda = {
        "Meta / WhatsApp": ["Sigue el README (sección «Arrancarlo»)"],
    }
    for grupo, vs in grupos.items():
        faltan = [k for k, v in vs.items() if not v]
        add(
            "Credenciales",
            grupo,
            MANUAL if faltan else OK,
            f"faltan {len(faltan)}/{len(vs)}: {', '.join(faltan)}"
            if faltan
            else "completas",
            ayuda[grupo] if faltan else [],
        )

    # La pasarela NO es un pendiente: es una decisión tomada (ADR 0011). Salía
    # aquí como «faltan 3/3» y parecía un paso que faltaba dar antes de vender,
    # cuando lo que hay que hacer es confirmar los abonos a mano en el panel.
    add(
        "Credenciales",
        "Pasarela de pago",
        OK,
        "no hace falta: los abonos los confirma una persona (ADR 0011)",
        [],
    )
    add(
        "Credenciales",
        "Quién confirma los abonos",
        MANUAL,
        "define quién mira el banco cada mañana y a qué hora",
        [
            "No es software: es un acuerdo. Escríbelo en docs/REGLAS_NEGOCIO.md",
            "El bot deja el pedido en EN_REVISION_PAGO y no produce solo",
        ],
    )

    url = s.public_url
    add(
        "Credenciales",
        "Túnel HTTPS público",
        OK if url.startswith("https://") else MANUAL,
        url or "sin definir",
        [] if url else ["ngrok http 8000", "y pon PUBLIC_URL=https://... en tu .env"],
    )


# === salida ================================================================


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="omite servicios y credenciales")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    check_python()
    check_deps()
    check_git()
    check_gitignore()
    check_pre_commit()
    check_env()
    check_settings()
    check_reglas()
    check_datos()
    check_cuentas()
    check_url_publica()
    check_lint()
    check_arquitectura()
    check_tests()
    if not args.local:
        check_docker()
        check_ollama()
        check_asesora_y_ventas()
        check_credenciales()

    if args.json:
        print(json.dumps([r.__dict__ for r in resultados], ensure_ascii=False, indent=2))
        return 0 if not any(r.estado == FALTA for r in resultados) else 1

    print(f"\n{C}{'=' * 74}\n  PREFLIGHT — FASE 0\n{'=' * 74}{RST}")
    grupo_actual = None
    for r in resultados:
        if r.grupo != grupo_actual:
            grupo_actual = r.grupo
            print(f"\n{B}{grupo_actual}{RST}")
        det = f"  {G}{r.detalle}{RST}" if r.detalle else ""
        print(f"  {ICONO[r.estado]} {r.nombre}{det}")
        for paso in r.arreglo:
            print(f"      {A}→{RST} {paso}")

    n_ok = sum(r.estado == OK for r in resultados)
    n_falta = sum(r.estado == FALTA for r in resultados)
    n_manual = sum(r.estado == MANUAL for r in resultados)

    print(f"\n{C}{'=' * 74}{RST}")
    print(
        f"  {V}{n_ok} OK{RST}   {R}{n_falta} FALTA{RST}   {A}{n_manual} MANUAL{RST}"
        f"   (de {len(resultados)})"
    )
    if n_falta == 0 and n_manual == 0:
        print(f"\n  {V}{B}✔ FASE 0 COMPLETA.{RST} Cierra con:  make ollama-check")
    elif n_falta == 0:
        print(
            f"\n  {A}Lo automatizable está listo.{RST} "
            f"Faltan {n_manual} paso(s) manual(es)."
        )
        print("  Guía paso a paso: README.md")
    else:
        print(
            f"\n  {R}Arregla primero los {n_falta} FALTA{RST} (cada uno trae su comando)."
        )
    print(f"{C}{'=' * 74}{RST}\n")
    return 1 if n_falta else 0


if __name__ == "__main__":
    raise SystemExit(main())
