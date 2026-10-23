"""Configuración por variables de entorno, tipada y validada al arrancar.

Por qué no `os.getenv` disperso por el código: con esto, si falta una variable
obligatoria el proceso NO ARRANCA, en vez de fallar a las 3 de la mañana en
mitad de un cobro. Fallar temprano y ruidosamente es una decisión de diseño.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parents[2]
#: Donde Camilo encuentra su Excel de ventas si no dice otra cosa.
EXCEL_DE_VENTAS = (
    Path.home() / "Documents" / "Luna Joyas" / "Ventas_LunaJoyas.xlsx"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # `populate_by_name` deja seguir construyendo Settings(...) por el
        # nombre del campo en los tests, aunque el campo tenga alias.
        populate_by_name=True,
    )

    entorno: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    #: Además de la consola, el registro del servidor en un archivo que rota
    #: (5 MB × 5). Es lo auditable: queda aunque se cierre la ventana. Vacío =
    #: solo consola.
    log_archivo: str = str(RAIZ / "logs" / "servidor.log")

    # --- selección de implementaciones (aquí es donde "migras") ---
    #: Dónde viven pedidos y clientas.
    #:   memory -> tests y demos. Se pierde todo al reiniciar.
    #:   sqlite -> el mismo archivo del resto del sistema. Es el de PRODUCCIÓN
    #:             mientras el negocio quepa en una máquina, que con 53
    #:             anillos al mes le sobra muchísimo.
    #:   sheets -> Fase 3, como espejo para el panel de operación.
    #:   sql    -> Fase 6, Postgres.
    #: Contraseña del panel del taller. Va en la URL para que Lía pueda
    #: guardarla como acceso directo en el celular y no escribirla cada vez.
    #:
    #: VACÍO = panel APAGADO. Es el valor por defecto a propósito: el panel
    #: muestra nombres, teléfonos y montos de las clientas, y el servidor se
    #: publica por un túnel. Un panel abierto por olvido es una fuga de datos,
    #: así que hay que encenderlo a mano.
    panel_token: str = ""

    #: URL pública desde la que Meta va a BAJAR las fotos y los videos.
    #:
    #: Tiene que ser la de ngrok (o la del dominio real en producción), porque
    #: los servidores de Meta hacen un GET desde internet: `localhost` no
    #: existe para ellos.
    #:
    #: ⚠️ NO la leas directamente: usa la propiedad `url_publica`, que cae
    #: sobre `PUBLIC_URL` cuando esta está vacía. Tener dos variables casi
    #: iguales fue un error de diseño, y costó una conversación entera de
    #: pruebas sin una sola foto: el túnel estaba puesto en `PUBLIC_URL` y
    #: las imágenes miraban esta otra.
    url_publica_override: str = Field(default="", alias="URL_PUBLICA")

    @property
    def url_publica(self) -> str:
        """La dirección por la que internet ve este servidor.

        Una sola respuesta para dos variables: si `URL_PUBLICA` está puesta
        manda ella (por si algún día las fotos se sirven desde otro sitio);
        si no, se usa el túnel de `PUBLIC_URL`, que es lo que hay el 99% de
        las veces.

        Que fueran dos ajustes independientes hacía que el bot arrancara
        «bien» —webhook OK, respuestas OK— y no mandara ni una foto, sin más
        pista que un WARNING por mensaje.
        """
        return (self.url_publica_override or self.public_url or "").rstrip("/")

    @property
    def imagenes_dir(self) -> Path:
        """Las imágenes del CATÁLOGO: muestrario y fotos de producto.

        Van en `data/` y versionadas en Git, no en la base de datos: son
        pocas, cambian poco, y que se revisen en un pull request vale más que
        poder cambiarlas desde una pantalla. Aquí está SOLO lo que se le manda a
        la clienta (02/10); lo que no se manda va en `fuentes/`.
        """
        return RAIZ / "data" / "imagenes"

    @property
    def imagenes_fuentes_dir(self) -> Path:
        """Lo que el bot USA pero no manda (02/10): la foto base y las máscaras
        con que se dibuja «así se te vería», y la foto original del muestrario
        que mide `vb muestrario`. Fuera de la carpeta de lo que se envía, para
        que `/media/…` no las sirva ni se confundan con lo que va a la clienta.
        """
        return self.imagenes_dir / "fuentes"

    @property
    def renders_dir(self) -> Path:
        """Las previsualizaciones que genera el bot. NO van en Git.

        Son derivadas: la misma combinación de colores da siempre el mismo
        archivo, así que borrarlas no pierde nada — se vuelven a dibujar la
        próxima vez que alguien pida esos colores.

        Junto a la base, como las fotos: en el servidor eso es el volumen
        `estado`. Antes vivían dentro del contenedor y cada despliegue las
        borraba: en el chat del panel las «así se te va a ver» viejas salían
        rotas (28/09). En el PC sigue siendo `data/renders`.
        """
        return self.sqlite_path.parent / "renders"

    @property
    def carpetas_de_media(self) -> tuple[Path, ...]:
        """Dónde buscar un archivo por su nombre lógico, en orden.

        Primero el catálogo (lo que está versionado y revisado), después las
        previsualizaciones. Así un nombre del catálogo nunca lo pisa un
        archivo generado.
        """
        return (self.imagenes_dir, self.renders_dir)

    @property
    def fotos_dir(self) -> Path:
        """Junto a la base de datos: si mueves `data/`, se mueve todo junto."""
        return self.sqlite_path.parent / "fotos"

    @property
    def marketing_dir(self) -> Path:
        """La carpeta de marketing que se ve en `/panel/marketing` (30/09–01/10).

        Es la de `Documents\\GitHub\\marketing-lia` (los .md y `datos/*.csv`), que
        escribe el Claude de marketing y sube `SUBIR-MARKETING.cmd`
        (`scripts/marketing.py --instalar`). Junto a la base: en el servidor,
        el volumen `estado`, que sobrevive a cada despliegue.
        """
        return self.sqlite_path.parent / "marketing" / "carpeta"

    @property
    def marketing_archivo(self) -> Path:
        """El tablero (`PARA-EL-PANEL.md`), dentro de esa carpeta."""
        return self.marketing_dir / "PARA-EL-PANEL.md"

    @property
    def marketing_foto_del_erp(self) -> Path:
        """Lo que el panel de marketing muestra del ERP (01/10): una foto que se
        toma al subir la carpeta y con el botón «Actualizar del ERP»."""
        return self.marketing_dir.parent / "erp.json"

    @property
    def finanzas_foto_del_erp(self) -> Path:
        """Lo que `/panel/finanzas` muestra del ERP (01/10): solo totales. La toman
        `vb erp --montar`, el botón «Actualizar del ERP» y el bot cada hora."""
        return self.sqlite_path.parent / "finanzas" / "erp.json"

    #: Quién conversa con la clienta (ADR 0014).
    #:   asesora   la IA (GPT, con Claude de respaldo) lee la conversación y
    #:             propone; Python valida y ejecuta. Necesita LLM_BACKEND=claude
    #:             y ANTHROPIC_API_KEY; sin ellas contesta el gestor por
    #:             etiquetas. Si ninguna IA contesta, el turno queda pendiente.
    #:   pipeline  el gestor por etiquetas de siempre, sin asesora.
    conversacion_motor: Literal["asesora", "pipeline"] = "asesora"
    repository_backend: Literal["memory", "sqlite", "sheets", "sql", "sap"] = "sqlite"
    #: La PRIMERA capa de modelo, la que entra cuando las reglas no bastan.
    #:   fake    sin modelo (tests)
    #:   ollama  el modelo local de `OLLAMA_MODEL`
    #:   claude  un modelo de Anthropic, el de `LLM_BASICO_MODEL`
    llm_backend: Literal["fake", "ollama", "claude", "openai"] = "fake"
    #: Qué modelo de Anthropic es la primera capa cuando `LLM_BACKEND=claude`.
    #: Haiku 5.5 (12/10): USD 0,10 / 0,50 por millón de tokens (10 veces menos
    #: que Haiku 4.5), ~3 s, y con el prompt en caché sale en torno a USD 0,0005
    #: por mensaje que de verdad lo necesita.
    llm_basico_model: str = "claude-haiku-5-5"
    #: El modelo que MIRA las fotos, si es de Anthropic («claude-haiku-5-5»).
    #: Vacío = el lector local de `OLLAMA_VISION_MODEL`, como siempre.
    llm_vision_model: str = ""
    #: Cuántas horas hacia atrás cuenta como CONTEXTO RECIENTE para el modelo
    #: potente. Un mensaje de hace tres días sobre otro anillo no ayuda a
    #: entender el de ahora: lo contamina.
    ventana_reciente_horas: float = Field(default=12.0, gt=0, le=168)
    #: Guardar el registro de cada decisión (capa, confianza, costo) en SQLite.
    #: No guarda textos ni teléfonos. Es lo que alimenta `vb metricas`.
    registrar_decisiones: bool = True
    payment_backend: Literal["fake", "bold", "wompi"] = "fake"
    # `console` imprime las respuestas en la terminal en vez de enviarlas por
    # WhatsApp. Es lo que te deja probar TODO el camino sin depender de Meta.
    channel_backend: Literal["console", "whatsapp"] = "console"

    #: El Excel de ventas (ADR 0015): una vista de la base que se actualiza sola.
    #: Las columnas verdes son de Camilo y vuelven a la base; las grises, del
    #: sistema. Ponlo dentro de OneDrive si quieres respaldo y verlo en el celular.
    ventas_excel: Path = EXCEL_DE_VENTAS
    #: Cada cuántos segundos se revisa si hay que actualizarlo. 0 = apagado.
    ventas_cada_s: float = Field(default=120.0, ge=0)

    @field_validator("ventas_excel", mode="before")
    @classmethod
    def _excel_vacio_es_el_de_siempre(cls, v):
        # `VENTAS_EXCEL=` vacío en el .env daría Path("") = la carpeta actual.
        return EXCEL_DE_VENTAS if v is None or str(v).strip() == "" else v

    # --- persistencia de la Fase 1 (dedupe, outbox, historial, checkpoints) ---
    sqlite_path: Path = RAIZ / "data" / "ventabot.db"
    dispatcher_interval_s: float = 1.0

    # --- rutas de datos y reglas ---
    reglas_path: Path = RAIZ / "config" / "reglas.yaml"
    catalogo_csv: Path = RAIZ / "data" / "catalogo.csv"
    #: Las promociones activas (17/10). Vacío = no hay ninguna.
    promociones_csv: Path = RAIZ / "data" / "promociones.csv"
    #: El banco de plantillas por situación (22/10) y los grupos que Camilo
    #: prendió. Sin archivo de activos, ninguno: el banco no manda nada solo.
    banco_plantillas_json: Path = RAIZ / "data" / "plantillas" / "banco.json"
    banco_plantillas_activos: Path = RAIZ / "data" / "plantillas" / "activos.json"
    fletes_csv: Path = RAIZ / "data" / "fletes.csv"

    # --- Meta / WhatsApp ---
    wa_phone_number_id: str = ""
    wa_access_token: str = ""
    wa_business_account_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""

    # --- Instagram (Fase 5) ---
    ig_account_id: str = ""
    ig_access_token: str = ""

    # --- túnel HTTPS público (Meta exige HTTPS con certificado válido) ---
    public_url: str = ""

    # --- pasarela ---
    bold_identity_key: str = ""
    bold_secret_key: str = ""
    bold_callback_url: str = ""
    wompi_public_key: str = ""
    wompi_private_key: str = ""
    wompi_integrity_secret: str = ""
    wompi_event_secret: str = ""

    # --- LLM ---
    ollama_host: str = "http://localhost:11434"
    # Portátil actual: Radeon 780M + 32 GB compartidos (Ollama por Vulkan).
    # gemma4:12b (7,6 GB) es el mejor en español de los que caben junto al de
    # visión. En un equipo de 4 GB de VRAM, bájalo a granite4.1:3b desde el .env.
    ollama_model: str = "gemma4:12b"
    #: El modelo que MIRA las fotos. Va aparte del de texto a propósito: son
    #: dos problemas distintos y se cambian por razones distintas (ver
    #: `app/domain/vision.py`). Vacío = sin ojos; el bot reconoce que llegó
    #: una foto, la marca para revisión humana y sigue.
    #:
    #: qwen3-vl:8b (6,1 GB) lee grabados y OCR mucho mejor que qwen2.5vl:3b y
    #: cabe junto al de texto en 32 GB. Bájalo con:
    #:     ollama pull qwen3-vl:8b
    ollama_vision_model: str = "qwen3-vl:8b"
    # ⚠️ Con <24 GB de VRAM, Ollama asigna 4K de contexto POR DEFECTO aunque el
    # modelo declare 128K, y el prompt desborda EN SILENCIO. Ver docs/MANUAL-VIVO.md.
    # 16384 sobra para el prompt + el schema. Con 32 GB compartidos se puede
    # subir a 32768 si `vb trazas` muestra que el bot pierde el hilo.
    ollama_num_ctx: int = Field(default=16384, ge=8000)

    #: El modelo GRANDE, para el segundo intento. Vacío = no hay segundo intento.
    #:
    #: ════════════════════════════════════════════════════════════════════════
    #: DOS MODELOS, Y EL CARO CASI NUNCA SE USA
    #: ════════════════════════════════════════════════════════════════════════
    #: El de siempre (`OLLAMA_MODEL`, 3B) contesta todos los turnos. Cuando NO
    #: entiende nada —y Python tampoco le saca ningún dato de la frase— es
    #: cuando el bot suelta «no te entendí» o repite la pregunta anterior, y
    #: son justo los turnos donde se pierde la venta.
    #:
    #: En ESOS turnos, y solo en esos, se vuelve a preguntar con este modelo, y
    #: además se le dan los últimos mensajes EN ORDEN. Sale caro por turno y
    #: barato al mes, porque el 3B resuelve la enorme mayoría.
    #:
    #: El historial NO se manda en el camino normal, y eso sigue siendo
    #: deliberado (ver `domain/contexto.py`): pegarle treinta mensajes a cada
    #: prompt cuesta tokens, se degrada al crecer y convierte un dato exacto en
    #: algo que el modelo tiene que deducir. Aquí se manda porque ya fallamos:
    #: la alternativa no es una respuesta mejor, es «no te entendí».
    #:
    #: Se elige el proveedor por el NOMBRE, sin una variable más:
    #:   · empieza por «claude» -> la API de Anthropic (hace falta la clave)
    #:   · cualquier otra cosa  -> un modelo de Ollama, en este mismo PC
    #:
    #: `claude-opus-5` es el más capaz y el que tiene sentido aquí: solo se
    #: llama en los turnos de rescate, así que se paga por turno rescatado y no
    #: por turno. Un modelo local grande (`granite4.1:8b`) también sirve y no
    #: cuesta dinero, pero con 4 GB de VRAM tira de CPU y se nota en la espera.
    llm_fuerte_model: str = ""

    #: La clave de la API de Anthropic. Solo hace falta si `llm_fuerte_model`
    #: es un modelo `claude-*`.
    #:
    #: Va en el `.env`, que está en `.gitignore` y tiene un test que lo vigila.
    #: NUNCA en el código: una clave en un commit se queda en el historial de
    #: Git para siempre, aunque se borre en el commit siguiente.
    anthropic_api_key: str = ""

    #: Cuánto se insiste DENTRO del turno si la IA no contesta, en segundos:
    #: Anthropic, respaldo, Anthropic… con esperas que crecen (29/09: el 503 de
    #: las 9:16 duró más que el segundo que se esperó). Si al final nadie
    #: contesta, el turno queda pendiente y se reintenta en segundo plano.
    ia_paciencia_s: float = Field(default=35.0, ge=0, le=300)
    #: El SEGUNDO proveedor de IA. Vacío = uno solo. `openai` = GPT, con
    #: `OPENAI_API_KEY` y `OPENAI_MODELO`.
    llm_respaldo_backend: str = ""
    #: Quién va PRIMERO: `anthropic` (lo de siempre) u `openai` (GPT primero y
    #: Anthropic de respaldo, desde el 29/09). El otro entra si el primero no
    #: contesta, en vueltas (`CadenaDeModelos`).
    ia_principal: str = "anthropic"
    openai_api_key: str = ""
    #: El de GPT para casi todo, y (opcional) uno más capaz para cuando duda.
    openai_modelo: str = ""
    openai_modelo_fuerte: str = ""
    #: Cuánto «piensa» cada uno (`none`, `low`, `medium`…). Vacío = el de fábrica.
    openai_esfuerzo: str = ""
    openai_esfuerzo_fuerte: str = ""

    # --- conversación ---
    #: Cuántos segundos se espera por si la clienta sigue escribiendo, para
    #: contestarle TODO de una vez en lugar de mensaje por mensaje.
    #:
    #: ════════════════════════════════════════════════════════════════════════
    #: POR QUÉ EXISTE ESTO (y por qué viene APAGADO)
    #: ════════════════════════════════════════════════════════════════════════
    #: Así escriben las clientas de verdad, sacado de una conversación textual:
    #:
    #:     «Son dos huellitas»
    #:     «Una huellita negra por mi panterita»
    #:     «Y la otra huellita no se jajaja»
    #:     «Tienes referencias de negro con otra huella»
    #:
    #: Cuatro mensajes que son UNA pregunta. Lía los leyó todos y contestó una
    #: vez; el bot contesta cuatro veces, y la tercera respuesta ya no tiene
    #: sentido porque llegó antes de leer la cuarta línea. Es lo que más delata
    #: que del otro lado hay una máquina.
    #:
    #: Es la CALMA que se espera: cada mensaje nuevo la reinicia, y nunca pasa
    #: de `agrupar_tope_segundos` desde el primero. El primer mensaje de una
    #: conversación no espera (la apertura sale al instante). Lo que llegue
    #: mientras el bot piensa se junta en el turno siguiente.
    #:
    #: En el código viene en 0 porque cuánto puede tardar el bot en contestar
    #: es una decisión del negocio: en producción lo pone `docker-compose.yml`
    #: (5 s desde el 27/09, medido sobre las ráfagas reales de 3-5 s).
    agrupar_segundos: float = Field(default=0.0, ge=0, le=60)
    #: Lo MÁS que se espera desde el primer mensaje de la ráfaga, aunque siga
    #: escribiendo. Sin tope, a quien escribe sin parar no se le contestaría.
    agrupar_tope_segundos: float = Field(default=15.0, ge=0, le=120)

    #: Regla de Lía (29/09): la talla la confirma ELLA en el panel antes del
    #: abono. El bot mira la foto de la regla, le dice a la clienta que en unos
    #: minutos se la confirman y sigue con los colores; no le dice ninguna talla.
    #: En el código viene en False (el flujo de antes); en producción, True.
    talla_la_confirma_lia: bool = False

    # --- infraestructura ---
    database_url: str = "postgresql://ventabot:ventabot@localhost:5432/ventabot"
    redis_url: str = "redis://localhost:6379/0"

    # --- observabilidad ---
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    #: Dónde se mandan las trazas. Vacío = la nube de LangSmith. Con un
    #: LangSmith propio corriendo en el PC, su dirección (por ejemplo
    #: http://localhost:1984). El código es el mismo en los dos casos.
    langsmith_endpoint: str = ""
    #: El proyecto donde se agrupan. Uno por entorno: mezclar las pruebas con
    #: las conversaciones de verdad hace inservible la vista.
    langsmith_project: str = "ventabot"
    langfuse_host: str = ""

    # --- CRM (Chatwoot) ---
    #: Dónde vive Chatwoot. Vacío = no se copia nada y el bot funciona igual.
    #: En el PC de Camilo, con el docker-compose de docker/chatwoot:
    #:     CHATWOOT_URL=http://localhost:3000
    chatwoot_url: str = ""
    #: Por dónde entra Lía a Chatwoot desde internet, para los enlaces del
    #: panel y del centro de mando. Vacío = la misma dirección pública del bot
    #: (con ngrok los dos comparten dominio). En el servidor, desde el 25/09:
    #:     CHATWOOT_URL_PUBLICA=https://chat.lunajoyas.example
    chatwoot_url_publica: str = ""
    #: Un «Access Token» de perfil (Chatwoot -> tu avatar -> Perfil).
    chatwoot_token: str = ""
    chatwoot_account_id: int = 1
    #: El buzón donde aparecen las conversaciones. Se crea una vez en
    #: Chatwoot como bandeja de tipo «API» y su número va aquí.
    chatwoot_inbox_id: int = 0
    #: Lo que protege `/webhook/chatwoot`, por donde entra lo que Lía escribe
    #: desde la bandeja. Vacío = ese webhook NO EXISTE (404), igual que el
    #: panel: encenderlo es una decisión, no un descuido.
    chatwoot_webhook_token: str = ""
    #: El token del agente bot «VentaBot» de Chatwoot. Lo que el bot copia sale
    #: firmado por él y no por la persona dueña de `chatwoot_token`: así Lía ve
    #: quién escribió cada cosa, y el webhook reconoce lo suyo sin adivinar.
    #: Lo crea y lo guarda `vb chatwoot --conectar`.
    chatwoot_bot_token: str = ""
    #: A quién se le asigna en Chatwoot lo que se contesta desde el PANEL (el
    #: panel no sabe quién está escribiendo). Es el id de la persona en Chatwoot
    #: (Lía). 0 = el bot solo se calla y no se asigna a nadie.
    chatwoot_persona_del_panel: int = 0

    # -- oídos: las notas de voz ------------------------------------------
    #: Quién transcribe las notas de voz. "ninguno" = se le pide a la clienta
    #: que lo escriba (lo de siempre). "groq" = Whisper en Groq, lo más barato
    #: que se midió (~US$0,04 por hora de audio).
    transcripcion_backend: Literal["ninguno", "groq"] = "ninguno"
    groq_api_key: str = ""
    groq_modelo_audio: str = "whisper-large-v3-turbo"

    # -- avisos al celular de quien opera ---------------------------------
    #: Por dónde llega el aviso cuando algo se rompe. "ninguno" = solo al log.
    #: "ntfy" no necesita cuenta: se instala la app y se suscribe al tema.
    avisos_backend: Literal["ninguno", "ntfy", "telegram"] = "ninguno"
    #: El tema de ntfy. Que sea largo y difícil de adivinar: quien lo sepa
    #: puede leer los avisos (por eso nunca llevan datos de clientas).
    ntfy_tema: str = ""
    ntfy_servidor: str = "https://ntfy.sh"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # -- recordatorios (04/10) ----------------------------------------------
    #: Escribirle a quien se quedó a medias antes del abono (talla, colores,
    #: grabado, resumen, abono): hasta dos por silencio dentro de la ventana
    #: de WhatsApp, solo a las 9 a. m. o a las 5 p. m. Reglas:
    #: `app/domain/recordatorios.py`.
    #: Apagado de fábrica (le escribe a clientas reales): lo enciende Camilo
    #: en producción (`docker-compose.yml`, 04/10).
    recordatorios: bool = False
    recordatorios_cada_s: float = Field(default=300.0, ge=60)
    #: El tercero, a los 3 días, con la plantilla `retomar_diseno`. Solo
    #: cuando Meta la aprobó (`vb recordatorios --plantilla` la crea y dice
    #: cómo va): con la plantilla sin aprobar, Meta rechaza el envío.
    recordatorio_con_plantilla: bool = False
    #: El dataset de MENSAJES de la cuenta de WhatsApp del bot en Meta (13/10):
    #: cada abono confirmado va ahí como `Purchase`, unido al clic del anuncio.
    #: Vacío = no se manda nada.
    meta_dataset_mensajes: str = ""
    #: La prueba de la primera respuesta (13/10): a «Quiero más información» se
    #: le abre con la foto de un anillo grabado y «¿Cómo se llama tu peludito?»;
    #: la presentación con precios va en su segundo mensaje. A quien pregunta el
    #: precio, la de siempre. False = la apertura de Lía de siempre.
    apertura_peludito: bool = False
    #: «dias» (13/10): por segmentos y días, con foto y botones
    #: (`app/domain/recordatorios_por_dias.py`). «horarios»: el de antes, a las
    #: 9 a. m. y 5 p. m. dentro de las 24 h.
    recordatorios_modo: str = "dias"

    # --- Google Sheets: el ERP del negocio (HUELLAS_ERP_v1) ---
    #: El JSON de la cuenta de servicio de Google (ver INSTRUCTIVO, paso del
    #: ERP). Sin él, el ERP no se toca y el bot funciona igual.
    google_service_account_json: Path | None = None
    #: El id del ERP: lo que va entre /d/ y /edit en su enlace de Google Sheets.
    sheets_spreadsheet_id: str = ""
    #: Cada cuánto se reconcilia el ERP aunque nadie mueva un pedido.
    erp_cada_s: float = Field(default=600.0, ge=60)
    #: Desde qué día (AAAA-MM-DD) las ventas del bot son de verdad (01/10). Vacío =
    #: todo lo del bot es de prueba, y el panel de marketing lo dice así en lo que
    #: muestra de él (ciudades, mezcla de huellitas, embudo). Se pone el día de
    #: «Pasar a real» (instructivo §10); desde ahí solo cuentan esas ventas.
    ventas_reales_desde: str = ""

    #: Secreto que se usa cuando META_APP_SECRET aún está vacío (Fase 1, con
    #: CHANNEL_BACKEND=console). Existe para que el simulador y el servidor
    #: firmen IGUAL; en cuanto pongas el secreto real de Meta, deja de usarse.
    SECRETO_DEV: ClassVar[str] = "ventabot-dev-sin-configurar"

    @property
    def app_secret_efectivo(self) -> str:
        """El secreto con el que se firman y verifican los webhooks.

        UN SOLO sitio lo resuelve. Antes el servidor y el simulador aplicaban
        cada uno su propio valor por defecto cuando la variable estaba vacía, y
        las firmas no cuadraban: el servidor rechazaba mensajes legítimos con
        403 y parecía un bug de criptografía.
        """
        return self.meta_app_secret or self.SECRETO_DEV

    @property
    def usando_secreto_de_desarrollo(self) -> bool:
        return not self.meta_app_secret

    def requiere_para_produccion(self) -> list[str]:
        """Variables que NO pueden estar vacías si `entorno == prod`."""
        faltantes = []
        if self.entorno != "prod":
            return faltantes
        obligatorias = {
            "wa_phone_number_id": self.wa_phone_number_id,
            "wa_access_token": self.wa_access_token,
            "meta_app_secret": self.meta_app_secret,
            "meta_verify_token": self.meta_verify_token,
        }
        if self.payment_backend == "bold":
            obligatorias |= {
                "bold_identity_key": self.bold_identity_key,
                "bold_secret_key": self.bold_secret_key,
                "bold_callback_url": self.bold_callback_url,
            }
        return [k for k, v in obligatorias.items() if not v]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    faltantes = s.requiere_para_produccion()
    if faltantes:
        raise RuntimeError(
            "Faltan variables obligatorias para entorno=prod: " + ", ".join(faltantes)
        )
    return s
