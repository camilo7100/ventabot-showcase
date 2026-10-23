"""Los pedidos sobreviven a un reinicio, y el candado de estado funciona.

Hasta ahora los pedidos vivían en memoria: apagar el servidor era perder las
ventas del día. Estos tests comprueban las dos cosas que hacen que una base
de datos sirva de algo:

  1. Que lo escrito siga ahí después de cerrar y volver a abrir el archivo.
  2. Que dos procesos no puedan avanzar el mismo pedido dos veces.

El punto 2 es el que impide despachar un anillo cobrado a medias cuando la
pasarela reintenta el webhook cinco veces, que es lo que hacen todas.
"""

from __future__ import annotations

import pytest

from app.adapters.repositories.sqlite_store import (
    SqliteCustomerRepository,
    SqliteDB,
    SqliteOrderRepository,
)
from app.domain.models import Channel, Customer, Order, OrderEvent, OrderItem
from app.domain.order_state import OrderState
from app.domain.personalizacion import ColorCircon, Huellita, Personalizacion
from app.domain.ports import ConflictoDeEstado


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "pedidos.db"


@pytest.fixture
def repo(ruta):
    return SqliteOrderRepository(SqliteDB(ruta))


def _pedido(**kw) -> Order:
    base = {
        "codigo": "PED-2026-0001",
        "customer_id": "c1",
        "estado": OrderState.COTIZADO.value,
        "items": [
            OrderItem(
                sku="ANI-HUE-1",
                nombre="Anillo huellita x1",
                cantidad=1,
                precio_unitario_cop=200_000,
            )
        ],
        "total_cop": 200_000,
        "anticipo_cop": 60_000,
        "saldo_cop": 140_000,
    }
    return Order(**{**base, **kw})


class TestSobreviveAlReinicio:
    def test_el_pedido_sigue_ahi_despues_de_cerrar_el_archivo(self, ruta):
        """LA razón de existir de este adaptador."""
        db = SqliteDB(ruta)
        repo = SqliteOrderRepository(db)
        pedido = repo.create(_pedido(), idem_key="k1")
        db.cerrar()

        # Como si hubieras apagado el servidor y lo hubieras vuelto a abrir.
        otro = SqliteOrderRepository(SqliteDB(ruta))
        recuperado = otro.get(pedido.id)
        assert recuperado is not None
        assert recuperado.codigo == "PED-2026-0001"
        assert recuperado.anticipo_cop == 60_000

    def test_la_personalizacion_tambien_sobrevive(self, ruta):
        """Si esto se pierde, hay que llamar a la clienta a preguntarle de
        qué color quería su anillo. Es la peor llamada posible."""
        db = SqliteDB(ruta)
        repo = SqliteOrderRepository(db)
        pedido = repo.create(_pedido(), idem_key="k1")
        repo.guardar_personalizacion(
            pedido.id,
            Personalizacion(
                talla=7,
                huellitas=[Huellita(corazon=ColorCircon.LILA, dedos=ColorCircon.MORADO)],
                grabados=["Rocky"],
            ),
        )
        db.cerrar()

        p = SqliteOrderRepository(SqliteDB(ruta)).get(pedido.id).items[0].personalizacion
        assert p.talla == 7
        assert p.huellitas[0].corazon is ColorCircon.LILA
        assert p.grabados == ["Rocky"]

    def test_la_marca_de_talla_por_revisar_no_se_pierde(self, ruta):
        db = SqliteDB(ruta)
        repo = SqliteOrderRepository(db)
        pedido = repo.create(_pedido(), idem_key="k1")
        repo.guardar_personalizacion(
            pedido.id,
            Personalizacion(talla=14, talla_revisar=True, talla_motivo="borde exterior"),
        )
        db.cerrar()

        p = SqliteOrderRepository(SqliteDB(ruta)).get(pedido.id).items[0].personalizacion
        assert p.talla_revisar is True
        assert p.talla_motivo == "borde exterior"


class TestBloqueoOptimista:
    """La defensa contra el webhook repetido."""

    def test_dos_veces_la_misma_transicion_falla_la_segunda(self, repo):
        pedido = repo.create(
            _pedido(estado=OrderState.ESPERANDO_ANTICIPO.value), idem_key="k"
        )
        repo.update_status(
            pedido.id,
            OrderState.ANTICIPO_PAGADO,
            expected_current=OrderState.ESPERANDO_ANTICIPO,
        )
        with pytest.raises(ConflictoDeEstado):
            repo.update_status(
                pedido.id,
                OrderState.ANTICIPO_PAGADO,
                expected_current=OrderState.ESPERANDO_ANTICIPO,
            )

    def test_el_estado_es_columna_y_no_solo_JSON(self, repo, ruta):
        """El candado es `WHERE estado = ?`. Si el estado viviera únicamente
        dentro del blob, no habría con qué cerrar el candado."""
        pedido = repo.create(_pedido(), idem_key="k")
        repo.update_status(
            pedido.id, OrderState.ESPERANDO_ANTICIPO, expected_current=OrderState.COTIZADO
        )
        filas = SqliteDB(ruta).consultar(
            "SELECT estado FROM orders WHERE id = ?", (pedido.id,)
        )
        assert filas[0]["estado"] == OrderState.ESPERANDO_ANTICIPO.value

    def test_un_pedido_que_no_existe_no_revienta_con_otra_cosa(self, repo):
        with pytest.raises(ConflictoDeEstado):
            repo.update_status(
                "nada", OrderState.EN_PRODUCCION, expected_current=OrderState.COTIZADO
            )


class TestIdempotencia:
    def test_crear_dos_veces_con_la_misma_clave_no_duplica(self, repo):
        """LangGraph re-ejecuta el nodo entero al reanudar: esto pasa solo."""
        uno = repo.create(_pedido(), idem_key="misma")
        dos = repo.create(_pedido(codigo="PED-2026-0002"), idem_key="misma")
        assert uno.id == dos.id
        assert repo.get_by_code("PED-2026-0002") is None

    def test_el_evento_de_auditoria_repetido_es_un_no_op(self, repo):
        pedido = repo.create(_pedido(), idem_key="k")
        evento = OrderEvent(
            order_id=pedido.id,
            estado_anterior="COTIZADO",
            estado_nuevo="ESPERANDO_ANTICIPO",
            actor="bot",
            idempotency_key="ev-1",
        )
        repo.append_event(evento)
        repo.append_event(evento)
        assert len(repo.eventos(pedido.id)) == 1

    def test_la_auditoria_conserva_el_orden(self, repo):
        pedido = repo.create(_pedido(), idem_key="k")
        for n, destino in enumerate(("ESPERANDO_ANTICIPO", "ANTICIPO_PAGADO")):
            repo.append_event(
                OrderEvent(
                    order_id=pedido.id,
                    estado_anterior=None,
                    estado_nuevo=destino,
                    actor="bot",
                    idempotency_key=f"ev-{n}",
                )
            )
        assert [e.estado_nuevo for e in repo.eventos(pedido.id)] == [
            "ESPERANDO_ANTICIPO",
            "ANTICIPO_PAGADO",
        ]


class TestBusquedas:
    def test_el_pedido_activo_es_el_mas_reciente_sin_cerrar(self, repo):
        repo.create(
            _pedido(codigo="PED-1", estado=OrderState.ENTREGADO.value), idem_key="a"
        )
        vivo = repo.create(_pedido(codigo="PED-2"), idem_key="b")
        assert repo.get_active_for_customer("c1").id == vivo.id

    def test_una_clienta_sin_pedidos_vivos_no_devuelve_uno_cerrado(self, repo):
        repo.create(
            _pedido(codigo="PED-1", estado=OrderState.CANCELADO.value), idem_key="a"
        )
        assert repo.get_active_for_customer("c1") is None

    def test_la_cola_de_tallas_por_revisar(self, repo):
        """La cola que hace viable «el bot decide y nadie se entera»."""
        claro = repo.create(_pedido(codigo="PED-1"), idem_key="a")
        dudoso = repo.create(_pedido(codigo="PED-2"), idem_key="b")
        repo.guardar_personalizacion(claro.id, Personalizacion(talla=7))
        repo.guardar_personalizacion(
            dudoso.id,
            Personalizacion(talla=14, talla_revisar=True, talla_motivo="borde exterior"),
        )
        pendientes = repo.con_talla_por_revisar()
        assert [o.codigo for o in pendientes] == ["PED-2"]

    def test_por_estado_sirve_de_panel(self, repo):
        repo.create(
            _pedido(codigo="PED-1", estado=OrderState.EN_PRODUCCION.value), idem_key="a"
        )
        repo.create(_pedido(codigo="PED-2"), idem_key="b")
        assert [o.codigo for o in repo.por_estado(OrderState.EN_PRODUCCION)] == ["PED-1"]


class TestClientas:
    def test_la_misma_persona_no_se_duplica(self, ruta):
        """Sin esto, cada mensaje crearía una clienta nueva y sus pedidos
        quedarían repartidos entre varias personas que son la misma."""
        repo = SqliteCustomerRepository(SqliteDB(ruta))
        uno = repo.upsert(
            Customer(
                channel=Channel.WHATSAPP, channel_user_id="573001112233", nombre="Ángela"
            )
        )
        dos = repo.upsert(
            Customer(
                channel=Channel.WHATSAPP,
                channel_user_id="573001112233",
                nombre="Angela R.",
            )
        )
        assert uno.id == dos.id
        assert repo.get(uno.id).nombre == "Angela R."

    def test_el_mismo_numero_en_otro_canal_es_otra_ficha(self, ruta):
        """[POR DEFINIR] Unificar identidades entre WhatsApp e Instagram es
        un problema aparte; hoy son dos fichas y no molesta a nadie."""
        repo = SqliteCustomerRepository(SqliteDB(ruta))
        wa = repo.upsert(Customer(channel=Channel.WHATSAPP, channel_user_id="X"))
        ig = repo.upsert(Customer(channel=Channel.INSTAGRAM, channel_user_id="X"))
        assert wa.id != ig.id

    def test_sobrevive_al_reinicio(self, ruta):
        db = SqliteDB(ruta)
        c = SqliteCustomerRepository(db).upsert(
            Customer(channel=Channel.WHATSAPP, channel_user_id="X", nombre="Ángela")
        )
        db.cerrar()
        assert SqliteCustomerRepository(SqliteDB(ruta)).get(c.id).nombre == "Ángela"


class TestConsultas:
    def test_los_huecos_del_NOT_IN_cuadran_con_los_estados(self):
        """Están escritos a mano para no armar SQL con cadenas. Si alguien
        agrega un estado cerrado y olvida el `?`, sqlite se queja de forma
        incomprensible; esto lo dice en castellano."""
        from app.adapters.repositories.sqlite_store import (
            ESTADOS_CERRADOS,
            SQL_PEDIDO_ACTIVO,
            SQL_PEDIDOS_ABIERTOS,
        )

        # SQL_PEDIDO_ACTIVO lleva un `?` de más: el del customer_id.
        assert SQL_PEDIDO_ACTIVO.count("?") == len(ESTADOS_CERRADOS) + 1
        assert SQL_PEDIDOS_ABIERTOS.count("?") == len(ESTADOS_CERRADOS)


class TestElContenedorLoEnchufa:
    """`REPOSITORY_BACKEND=sqlite` tiene que dar de verdad los adaptadores de
    SQLite. Un backend que se declara y no se cablea es peor que no tenerlo:
    el sistema arranca en verde y pierde los pedidos igual."""

    def test_sqlite_devuelve_los_repositorios_de_sqlite(self, monkeypatch, tmp_path):
        import app.infra.container as contenedor
        from app.infra.settings import get_settings

        monkeypatch.setenv("REPOSITORY_BACKEND", "sqlite")
        monkeypatch.setenv("CHANNEL_BACKEND", "console")
        monkeypatch.setenv("LLM_BACKEND", "fake")
        monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
        get_settings.cache_clear()
        contenedor._singleton = None
        try:
            c = contenedor.get_container()
            assert isinstance(c.orders, SqliteOrderRepository)
            assert isinstance(c.customers, SqliteCustomerRepository)
        finally:
            get_settings.cache_clear()
            contenedor._singleton = None

    def test_sqlite_es_el_valor_POR_DEFECTO(self):
        """Perder las ventas del día por no haber puesto una variable de
        entorno no puede ser el comportamiento por defecto."""
        from app.infra.settings import Settings

        assert "sqlite" in str(Settings.model_fields["repository_backend"].default)
