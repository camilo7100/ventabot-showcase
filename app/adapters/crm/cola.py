"""La cola de lo que falta copiar a Chatwoot.

Chatwoot es la ÚNICA forma en que Camilo y Lía ven la charla (07/10): lo que
no llega ahí es como si no hubiera pasado. Por eso la cola vive en la base de
datos y no en la memoria del proceso: si Chatwoot se cae por horas, o el bot se
reinicia, o el que encoló era un script que ya terminó, cada copia sigue ahí
hasta que Chatwoot la recibe. Sin tope de tiempo.

Una sola copia a la vez y en orden (la más vieja primero), aunque haya dos
procesos mirando la misma cola (el servidor y un script): quien la toma la
«reserva» un rato y nadie más la toca mientras tanto. Así no sale nada repetido
ni desordenado.

Cada tarea es una lista JSON: `[tipo, conversation_id, ...]`.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

#: Cuánto dura la reserva de una copia mientras se manda. Muy por encima de lo
#: que tarda una subida (30 s con archivos): si el proceso que la tomó se muere
#: a la mitad, otro la retoma pasado este rato.
RESERVA = timedelta(minutes=2)

ESQUEMA = """
CREATE TABLE IF NOT EXISTS chatwoot_pendientes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    tarea           TEXT NOT NULL,
    creada          TEXT NOT NULL,
    intentos        INTEGER NOT NULL DEFAULT 0,
    ultimo_error    TEXT NOT NULL DEFAULT '',
    -- 1 = Chatwoot la rechazó por sí misma (no por estar caído): se aparta
    -- para que no tape a las demás, y queda aquí para mirarla.
    apartada        INTEGER NOT NULL DEFAULT 0,
    dueno           TEXT,
    hasta           TEXT
);
"""


@dataclass(frozen=True)
class Pendiente:
    id: int
    tarea: list
    creada: datetime
    intentos: int


def _ahora() -> datetime:
    return datetime.now(UTC)


def _a_json(tarea) -> str:
    # `default=str`: una fecha o algo raro en los atributos no puede hacer que
    # la copia no se guarde.
    return json.dumps(list(tarea), ensure_ascii=False, default=str)


class ColaEnSqlite:
    """La de verdad: sobrevive caídas y reinicios."""

    def __init__(self, db) -> None:
        self._db = db
        self._dueno = uuid.uuid4().hex
        self._db.ejecutar(ESQUEMA)

    def poner(self, tarea) -> None:
        self._db.ejecutar(
            "INSERT INTO chatwoot_pendientes (conversation_id, tarea, creada) "
            "VALUES (?, ?, ?)",
            (str(tarea[1]), _a_json(tarea), _ahora().isoformat()),
        )

    def tomar(self) -> Pendiente | None:
        """La más vieja, si nadie más la tiene. Si la tiene otro, nada: el orden
        se respeta aunque eso signifique esperar."""
        ahora = _ahora()
        self._db.ejecutar(
            "UPDATE chatwoot_pendientes SET dueno = ?, hasta = ? "
            "WHERE id = (SELECT MIN(id) FROM chatwoot_pendientes WHERE apartada = 0) "
            "AND (hasta IS NULL OR hasta < ? OR dueno = ?)",
            (self._dueno, (ahora + RESERVA).isoformat(), ahora.isoformat(), self._dueno),
        )
        filas = self._db.consultar(
            "SELECT id, tarea, creada, intentos FROM chatwoot_pendientes "
            "WHERE dueno = ? AND apartada = 0 ORDER BY id LIMIT 1",
            (self._dueno,),
        )
        if not filas:
            return None
        f = filas[0]
        return Pendiente(
            f["id"],
            json.loads(f["tarea"]),
            datetime.fromisoformat(f["creada"]),
            f["intentos"],
        )

    def hecha(self, id_: int) -> None:
        self._db.ejecutar("DELETE FROM chatwoot_pendientes WHERE id = ?", (id_,))

    def fallo(self, id_: int, error: str) -> None:
        """No llegó: vuelve a la fila, primera, y se suelta la reserva."""
        self._db.ejecutar(
            "UPDATE chatwoot_pendientes SET intentos = intentos + 1, "
            "ultimo_error = ?, dueno = NULL, hasta = NULL WHERE id = ?",
            (error[:500], id_),
        )

    def apartar(self, id_: int, error: str) -> None:
        self._db.ejecutar(
            "UPDATE chatwoot_pendientes SET apartada = 1, intentos = intentos + 1, "
            "ultimo_error = ?, dueno = NULL, hasta = NULL WHERE id = ?",
            (error[:500], id_),
        )

    def pendientes(self) -> int:
        fila = self._db.consultar(
            "SELECT COUNT(*) AS n FROM chatwoot_pendientes WHERE apartada = 0"
        )
        return int(fila[0]["n"])

    def soltar(self) -> None:
        """Al cerrar: lo que este proceso tenía reservado, que otro lo tome ya."""
        self._db.ejecutar(
            "UPDATE chatwoot_pendientes SET dueno = NULL, hasta = NULL WHERE dueno = ?",
            (self._dueno,),
        )


class ColaEnMemoria:
    """Para las pruebas y para un proceso sin base de datos. Misma interfaz;
    las tareas pasan igual por JSON, para que una que no se pueda guardar se
    note aquí también."""

    def __init__(self, maximo: int = 500) -> None:
        self._filas: list[tuple[int, str, datetime, int]] = []
        self._siguiente = 1
        self._maximo = maximo
        self._candado = threading.Lock()

    def poner(self, tarea) -> None:
        with self._candado:
            if len(self._filas) >= self._maximo:
                raise OverflowError("la cola en memoria está llena")
            self._filas.append((self._siguiente, _a_json(tarea), _ahora(), 0))
            self._siguiente += 1

    def tomar(self) -> Pendiente | None:
        with self._candado:
            if not self._filas:
                return None
            id_, tarea, creada, intentos = self._filas[0]
        return Pendiente(id_, json.loads(tarea), creada, intentos)

    def _quitar(self, id_: int) -> None:
        with self._candado:
            self._filas = [f for f in self._filas if f[0] != id_]

    def hecha(self, id_: int) -> None:
        self._quitar(id_)

    def fallo(self, id_: int, error: str) -> None:
        with self._candado:
            self._filas = [
                (i, t, c, n + 1) if i == id_ else (i, t, c, n)
                for i, t, c, n in self._filas
            ]

    def apartar(self, id_: int, error: str) -> None:
        self._quitar(id_)

    def pendientes(self) -> int:
        with self._candado:
            return len(self._filas)

    def soltar(self) -> None:
        return None

    def vaciar_todo(self) -> None:
        with self._candado:
            self._filas = []
