"""Lo que necesitan los recordatorios de la base (04/10). Solo eso.

- `RegistroDeRecordatorios`: qué recordatorio se le mandó a qué charla y por
  cuál silencio (su «ancla»: el último mensaje de ella). Vive en la base y no
  en memoria a propósito: un servidor que se reinicia no le vuelve a escribir
  a nadie.
- `CharlasParaRecordar`: las charlas de los últimos días (`DIAS_ATRAS`) y, de
  cada una, lo que hace falta para decidir (quién habló de último, cuándo,
  cuántos mensajes escribió ella). Solo lectura.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.adapters.repositories.sqlite_store import SqliteDB

#: Hasta cuántos días atrás se miran las charlas (el tercero va a los 3 días;
#: con margen por si el servidor estuvo caído).
DIAS_ATRAS = 5

ESQUEMA = """
CREATE TABLE IF NOT EXISTS recordatorios_24h (
    conversation_id TEXT NOT NULL,
    ancla           TEXT NOT NULL,
    numero          INTEGER NOT NULL,
    etapa           TEXT NOT NULL,
    enviado_en      TEXT NOT NULL,
    PRIMARY KEY (conversation_id, ancla, numero)
);
"""


class RegistroDeRecordatorios:
    def __init__(self, db: SqliteDB) -> None:
        self._db = db
        self._db.ejecutar(ESQUEMA)

    def enviados(self, conversation_id: str, ancla: str) -> dict[int, datetime]:
        """{número: cuándo} de los que ya salieron por ESTE silencio."""
        filas = self._db.consultar(
            "SELECT numero, enviado_en FROM recordatorios_24h "
            "WHERE conversation_id = ? AND ancla = ?",
            (conversation_id, ancla),
        )
        return {int(f["numero"]): datetime.fromisoformat(f["enviado_en"]) for f in filas}

    def ultima_plantilla(self, conversation_id: str) -> datetime | None:
        """Cuándo se le mandó la última plantilla (por cualquier silencio)."""
        filas = self._db.consultar(
            "SELECT MAX(enviado_en) AS cuando FROM recordatorios_24h "
            "WHERE conversation_id = ? AND numero = 3",
            (conversation_id,),
        )
        cuando = filas[0]["cuando"] if filas else None
        return datetime.fromisoformat(cuando) if cuando else None

    def anotar(self, conversation_id: str, ancla: str, numero: int, etapa: str) -> bool:
        """True si quedó anotado ahora (False: ya estaba; no se manda dos veces)."""
        cursor = self._db.ejecutar(
            "INSERT OR IGNORE INTO recordatorios_24h "
            "(conversation_id, ancla, numero, etapa, enviado_en) VALUES (?,?,?,?,?)",
            (conversation_id, ancla, numero, etapa, datetime.now(UTC).isoformat()),
        )
        return cursor.rowcount == 1

    def ultimos(self, limite: int = 50) -> list[dict]:
        """Los últimos mandados (para el panel y `vb recordatorios`)."""
        return [
            dict(f)
            for f in self._db.consultar(
                "SELECT conversation_id, numero, etapa, enviado_en "
                "FROM recordatorios_24h ORDER BY enviado_en DESC LIMIT ?",
                (limite,),
            )
        ]


class CharlasParaRecordar:
    def __init__(self, db: SqliteDB) -> None:
        self._db = db

    def recientes(self) -> list[str]:
        """Las charlas en las que ella escribió en los últimos `DIAS_ATRAS` días."""
        # `ventana_24h_hasta` = su último mensaje + 24 h.
        desde = (datetime.now(UTC) - timedelta(days=DIAS_ATRAS - 1)).isoformat()
        return [
            f["conversation_id"]
            for f in self._db.consultar(
                "SELECT conversation_id FROM conversations WHERE ventana_24h_hasta > ? "
                "ORDER BY ventana_24h_hasta",
                (desde,),
            )
        ]

    def estado_para_recordar(self, conversation_id: str) -> dict | None:
        """Quién habló de último y cuándo, y lo de ella (sin guardar nada)."""
        conv = self._db.consultar(
            "SELECT ultimo_entrante FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        # Un sticker o una reacción sola no pide respuesta: no cuenta como «lo
        # último lo dijo ella» (Mónica, 07/10: cerró con un sticker y el
        # recordatorio de las 9 a. m. no se habría programado).
        ultimo = self._db.consultar(
            "SELECT direccion, created_at FROM messages WHERE conversation_id = ? "
            "AND NOT (direccion = 'IN' AND COALESCE(texto, '') = '' AND ("
            'payload LIKE \'%"type": "sticker"%\' '
            'OR payload LIKE \'%"type": "reaction"%\')) '
            "ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        )
        if not conv or not ultimo:
            return None
        suyos = self._db.consultar(
            "SELECT texto FROM messages WHERE conversation_id = ? AND direccion = 'IN' "
            "ORDER BY id",
            (conversation_id,),
        )
        con_texto = [f["texto"] for f in suyos if (f["texto"] or "").strip()]
        return {
            "direccion": ultimo[0]["direccion"],
            "created_at": ultimo[0]["created_at"],
            "ultimo_entrante": conv[0]["ultimo_entrante"],
            "mensajes_de_ella": len(suyos),
            "primer_mensaje": suyos[0]["texto"] or "" if suyos else "",
            # Sus últimos mensajes con texto: «mañana le consigno» + «ahora no
            # me queda fácil» + «muchas gracias» -> pidió tiempo.
            "texto_de_ella": "\n".join(con_texto[-3:]),
        }
