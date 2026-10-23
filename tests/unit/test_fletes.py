"""El flete sale de un ARCHIVO que Camilo edita, no de un número en el código.

Por qué esto tiene su propio archivo de pruebas
===============================================
`data/fletes.csv` llevaba meses en el repositorio, con 29 ciudades y sus
tarifas, y NADIE lo leía: el bot cotizaba $16.500 a todo el mundo porque ese
número estaba escrito a mano en tres sitios distintos del código.

Eso costaba plata en las dos direcciones. A una clienta de Bogotá se le
cobraba casi el doble de lo que cuesta mandárselo; a una de Leticia se le
cobraba un tercio de lo que cuesta, y la diferencia la ponía Lía.

Lo que se prueba aquí es la cadena entera, porque el fallo no estaba en
ninguna pieza: estaba en que las piezas no estaban conectadas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.repositories.csv_files import CsvFletes
from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
)
from app.conversacion.ejecutor import Ejecutor
from app.conversacion.interprete import Interprete
from app.conversacion.mundo import Mundo
from app.conversacion.pipeline import Pipeline
from app.conversacion.redactor import Redactor
from app.domain.models import Channel, Customer
from tests.unit.test_inteligencia_conversacional import (
    CONV,
    ContextoEnMemoria,
    ModeloDeMadera,
    _productos,
)

CSV = Path(__file__).resolve().parents[2] / "data" / "fletes.csv"

#: Una tabla de mentira CON precios distintos por ciudad. El mecanismo se
#: prueba aquí y no contra `data/fletes.csv`: ese archivo es de Lía y cambia
#: cuando ella cambia de tarifa (hoy cobra lo mismo a todo el país). Un test
#: del mecanismo que se cae porque Lía unificó sus precios no está probando el
#: mecanismo: está probando el precio, y eso se prueba aparte, abajo.
CSV_DE_MENTIRA = """ciudad,departamento,zona,costo_cop,dias_transporte
(DEFECTO),,NACIONAL,15000,4
Bogotá,Cundinamarca,LOCAL,8000,1
Leticia,Amazonas,ESPECIAL,45000,8
"""


@pytest.fixture
def tabla() -> CsvFletes:
    return CsvFletes(CSV)


@pytest.fixture
def tabla_de_mentira(tmp_path) -> CsvFletes:
    ruta = tmp_path / "fletes.csv"
    ruta.write_text(CSV_DE_MENTIRA, encoding="utf-8")
    return CsvFletes(ruta)


class TestElArchivo:
    def test_existe_y_se_puede_leer(self, tabla):
        assert tabla.ciudades(), "data/fletes.csv no trae ni una ciudad"

    def test_los_comentarios_no_rompen_la_lectura(self, tabla):
        """El archivo lleva instrucciones para Camilo en líneas que empiezan
        por `#`. Si el lector no las salta, el archivo documentado no sirve."""
        assert "#" in CSV.read_text(encoding="utf-8")
        assert tabla.costo_por_defecto > 0

    def test_el_defecto_sale_del_archivo_y_es_el_nacional(self, tabla):
        """Hoy Lía cobra UNA tarifa nacional: $18.000 (Camilo, 20/09).

        Y tiene que poder cambiarla sin programar: por eso vive en una fila
        del CSV y no en una constante. La constante del código es solo el
        último recurso si el archivo no se puede leer, y dice lo mismo.
        """
        from app.domain.faq import ENVIO_NACIONAL_COP

        assert tabla.costo_por_defecto == 17_500 == ENVIO_NACIONAL_COP

    def test_hoy_todas_las_ciudades_pagan_lo_mismo(self, tabla):
        """El bot llegó a cotizar $8.000 a Bogotá y $14.000 a otra el mismo
        día, con las filas viejas del CSV. Lía cobra una sola tarifa."""
        costos = {tabla.buscar(c).costo_cop for c in tabla.ciudades()}
        assert costos == {17_500}, f"hay ciudades con otra tarifa: {costos}"

    def test_la_fila_DEFECTO_no_se_le_ofrece_a_nadie_como_ciudad(self, tabla):
        assert CsvFletes.FILA_POR_DEFECTO not in tabla.ciudades()

    def test_ninguna_tarifa_es_absurda(self, tabla):
        """Un cero se teclea sin querer y regala el envío a todo el país."""
        for ciudad in tabla.ciudades():
            costo = tabla.buscar(ciudad).costo_cop
            assert 5_000 <= costo <= 60_000, f"{ciudad} tiene un flete raro: {costo}"


class TestLaBusqueda:
    @pytest.mark.parametrize(
        "escrito", ["Medellín", "medellin", "MEDELLIN", "  Medellin  "]
    )
    def test_da_igual_como_lo_escriba_la_clienta(self, tabla, escrito):
        assert tabla.buscar(escrito).costo_cop == tabla.buscar("Medellín").costo_cop

    def test_un_pueblo_que_no_esta_no_tumba_el_pedido(self, tabla):
        """Colombia tiene 1.100 municipios. La tabla no los va a tener todos,
        y una venta no se puede caer porque falte uno."""
        f = tabla.buscar("Sabana de Torres")
        assert f.costo_cop == tabla.costo_por_defecto

    def test_sin_ciudad_tambien_cotiza(self, tabla):
        assert tabla.buscar(None).costo_cop == tabla.costo_por_defecto


class TestLaCadenaCompleta:
    """De «soy de Bogotá» al número que ve la clienta."""

    def _bot(self, con_tabla: bool):
        customers = InMemoryCustomerRepository()
        customers.upsert(
            Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
        )
        mundo = Mundo(
            InMemoryOrderRepository(),
            customers,
            _productos(),
            ContextoEnMemoria(),
            fletes=CsvFletes(CSV) if con_tabla else None,
        )
        return Pipeline(
            Interprete(ModeloDeMadera(), "", ""), mundo, Ejecutor(mundo), Redactor()
        ), mundo

    def test_sin_tabla_el_bot_sigue_vendiendo(self):
        """Que falte el CSV no puede dejar a Lía sin vender en toda la mañana."""
        from app.domain.faq import ENVIO_NACIONAL_COP

        _, mundo = self._bot(con_tabla=False)
        assert mundo.envio_a("Bogotá") == ENVIO_NACIONAL_COP

    def test_con_tabla_cada_ciudad_paga_LO_QUE_DIGA_LA_TABLA(self, tabla_de_mentira):
        """El mecanismo, con precios inventados: lo que importa es que lea la
        fila de ESA ciudad y no una constante."""
        from app.adapters.repositories.memory import InMemoryCustomerRepository

        mundo = Mundo(
            InMemoryOrderRepository(),
            InMemoryCustomerRepository(),
            _productos(),
            ContextoEnMemoria(),
            fletes=tabla_de_mentira,
        )
        assert mundo.envio_a("Bogotá") == 8_000
        assert mundo.envio_a("Leticia") == 45_000
        assert mundo.envio_a(None) == 15_000

    def test_con_la_tabla_de_verdad_todos_pagan_el_nacional(self):
        """Y hoy, con el archivo de Lía, a todo el mundo le sale lo mismo."""
        from app.domain.faq import ENVIO_NACIONAL_COP

        _, mundo = self._bot(con_tabla=True)
        assert mundo.envio_a("Bogotá") == ENVIO_NACIONAL_COP
        assert mundo.envio_a("Leticia") == ENVIO_NACIONAL_COP
        assert mundo.envio_a(None) == ENVIO_NACIONAL_COP

    def test_una_tabla_rota_no_tumba_la_cotizacion(self):
        """Si alguien deja el CSV a medias, se cotiza el nacional y sigue."""

        from app.domain.faq import ENVIO_NACIONAL_COP

        class TablaRota:
            costo_por_defecto = ENVIO_NACIONAL_COP

            def buscar(self, ciudad):
                return None  # sin `.costo_cop`

        mundo = Mundo(
            InMemoryOrderRepository(),
            InMemoryCustomerRepository(),
            _productos(),
            ContextoEnMemoria(),
            fletes=TablaRota(),
        )
        from app.domain.faq import ENVIO_NACIONAL_COP as NACIONAL

        assert mundo.envio_a("Bogotá") == NACIONAL

    def test_le_contesta_el_flete_DE_SU_CIUDAD(self):
        """El defecto que de verdad importa: la cifra sale de la TABLA, no de
        un número escrito a mano. Hoy la tabla dice lo mismo para todos."""
        bot, mundo = self._bot(con_tabla=True)
        bot.ejecutar(CONV, "hola, soy de Bogotá")
        texto = bot.ejecutar(CONV, "cuánto vale el envío?").respuesta.texto_plano
        esperado = f"${mundo.envio_a('Bogotá'):,.0f}".replace(",", ".")
        assert esperado in texto, texto
        assert "$8.000" not in texto, "esa era la tarifa vieja de Bogotá"

    def test_sin_decir_ciudad_contesta_el_nacional(self):
        bot, mundo = self._bot(con_tabla=True)
        texto = bot.ejecutar(CONV, "cuánto vale el envío?").respuesta.texto_plano
        esperado = f"${mundo.envio_a(None):,.0f}".replace(",", ".")
        assert esperado in texto, texto

    def test_el_hueco_del_texto_nunca_le_llega_a_la_clienta(self):
        bot, _ = self._bot(con_tabla=True)
        texto = bot.ejecutar(CONV, "cuánto vale el envío?").respuesta.texto_plano
        assert "{envio}" not in texto
