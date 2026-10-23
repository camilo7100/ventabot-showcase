"""Tests de la configuración y los datos semilla.

Estos tests son baratos y atrapan la clase de error que más duele: un typo en
un CSV o en el YAML que nadie nota hasta que cotizas mal un pedido real.

Además funcionan como CONTRATO de los datos: si mañana editas
`data/catalogo.csv` en Excel y rompes una columna, CI te avisa.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.adapters.repositories.csv_files import CsvFletes, cargar_catalogo_csv
from app.infra.reglas import cargar_reglas, marcadores_por_definir

RAIZ = Path(__file__).resolve().parents[2]
REGLAS = RAIZ / "config" / "reglas.yaml"
CATALOGO = RAIZ / "data" / "catalogo.csv"
FLETES = RAIZ / "data" / "fletes.csv"


@pytest.fixture(scope="module")
def reglas():
    return cargar_reglas(REGLAS)


@pytest.fixture(scope="module")
def catalogo():
    return cargar_catalogo_csv(CATALOGO)


class TestReglas:
    def test_el_yaml_valida_contra_el_modelo(self, reglas):
        assert reglas.negocio.moneda == "COP"

    def test_anticipo_entre_0_y_1(self, reglas):
        assert Decimal("0") <= reglas.pagos.anticipo_pct_default <= Decimal("1")

    def test_el_bot_no_negocia_descuentos_solo(self, reglas):
        """Decisión de v1: todo descuento pasa por un humano.

        Si algún día lo cambias, que sea a propósito y no por accidente.
        """
        assert reglas.conversacion.descuento_maximo_automatico_pct == Decimal("0")

    def test_el_anticipo_no_se_acepta_por_transferencia(self, reglas):
        """La defensa nº1 contra el fraude de comprobantes falsos (ADR 0003).

        Si este test falla es porque alguien activó la transferencia para el
        anticipo. Puede ser legítimo, pero tiene que ser una decisión consciente.
        """
        assert reglas.pagos.permitir_transferencia_para_anticipo is False

    def test_max_productos_respeta_el_limite_de_whatsapp(self, reglas):
        """Una lista interactiva de WhatsApp admite 10 filas. Ni una más."""
        assert 1 <= reglas.conversacion.max_productos_por_mensaje <= 10

    def test_se_escala_a_humano_antes_de_insistir(self, reglas):
        assert 1 <= reglas.conversacion.fallos_nlu_antes_de_handoff <= 3

    def test_hay_marcadores_por_definir_documentados(self):
        """No es un fallo: es un recordatorio visible de lo que sigue supuesto."""
        pendientes = marcadores_por_definir(REGLAS)
        assert pendientes, "sin marcadores: ¿ya definiste todo, o los borraste?"

    def test_recordatorios_en_orden_creciente(self, reglas):
        for lista in (
            reglas.pagos.recordatorio_anticipo_horas,
            reglas.pagos.recordatorio_saldo_horas,
        ):
            assert lista == sorted(lista)
            assert all(h > 0 for h in lista)

    def test_se_cancela_despues_del_ultimo_recordatorio(self, reglas):
        assert reglas.pagos.cancelar_por_falta_de_anticipo_horas > max(
            reglas.pagos.recordatorio_anticipo_horas
        )


class TestCatalogo:
    def test_carga_y_tiene_productos_activos(self, catalogo):
        # Tres productos REALES valen más que cinco inventados: el catálogo
        # es el de Luna Joyas (anillo de 1, 2 y 3 huellitas).
        assert len(catalogo) >= 3
        assert any(p.activo for p in catalogo)

    def test_skus_unicos(self, catalogo):
        skus = [p.sku for p in catalogo]
        assert len(skus) == len(set(skus))

    def test_todos_los_precios_son_enteros_positivos(self, catalogo):
        for p in catalogo:
            assert isinstance(p.precio_cop, int) and p.precio_cop > 0, p.sku

    def test_todos_tienen_nombre(self, catalogo):
        for p in catalogo:
            assert p.nombre.strip(), p.sku

    def test_dias_de_produccion_razonables(self, catalogo):
        for p in catalogo:
            assert 0 < p.dias_produccion <= 60, p.sku

    def test_anticipo_por_producto_entre_0_y_1(self, catalogo):
        for p in catalogo:
            assert Decimal("0") < p.anticipo_pct <= Decimal("1"), p.sku

    def test_un_csv_roto_falla_ruidosamente(self, tmp_path):
        """Mejor no arrancar que cotizar mal."""
        malo = tmp_path / "malo.csv"
        malo.write_text(
            "sku,nombre,precio_cop,dias_produccion\nX-1,Cosa,no-es-un-numero,5\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="línea 2"):
            cargar_catalogo_csv(malo)

    def test_un_csv_con_skus_duplicados_falla(self, tmp_path):
        malo = tmp_path / "dup.csv"
        malo.write_text(
            "sku,nombre,precio_cop,dias_produccion\nX-1,Cosa,1000,5\nX-1,Otra,2000,5\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="duplicados"):
            cargar_catalogo_csv(malo)


@pytest.fixture(scope="module")
def fletes():
    # Sin defaults a mano: los trae la fila `(DEFECTO)` del propio CSV.
    return CsvFletes(FLETES)


class TestLoQueNuncaEntraAlRepositorio:
    """Un `git add -A` distraído es todo lo que hace falta para publicar algo
    que no se puede despublicar. El historial de Git no olvida.

    Esto ya pasó dos veces: un `git commit` chocó con el hook de archivos
    grandes por una foto de 3,5 MB en `data/fotos/`. El hook hizo bien su
    trabajo, pero lo grave no era el tamaño: eran comprobantes de
    transferencia de clientas, con nombre, cuenta y monto, a punto de quedar
    en el repositorio para siempre.
    """

    @pytest.fixture
    def gitignore(self) -> str:
        return (RAIZ / ".gitignore").read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "patron,por_que",
        [
            (".env", "los tokens de Meta"),
            ("credentials", "las claves de Google"),
            ("data/fotos", "los comprobantes y las fotos de las clientas"),
            ("data/ventabot.db", "los pedidos y los datos de las clientas"),
            ("data/webhook_log.jsonl", "el registro de mensajes entrantes"),
        ],
    )
    def test_esta_ignorado(self, gitignore, patron, por_que):
        assert patron in gitignore, f"{patron} lleva {por_que} y NO está ignorado"


class TestFletes:
    def test_cubre_las_ciudades_principales(self, fletes):
        ciudades = {CsvFletes.normalizar(c) for c in fletes.ciudades()}
        for c in ("bogota", "medellin", "cali", "barranquilla", "bucaramanga"):
            assert c in ciudades

    @pytest.mark.parametrize(
        "escrito", ["Medellín", "medellin", "MEDELLÍN", "  Medellin  "]
    )
    def test_busqueda_insensible_a_tildes_y_mayusculas(self, fletes, escrito):
        assert fletes.buscar(escrito).costo_cop == fletes.costo_por_defecto

    def test_una_ciudad_desconocida_no_tumba_el_pedido(self, fletes):
        """Nadie pierde una venta porque el cliente escribió un pueblo raro."""
        f = fletes.buscar("Pueblo Que No Existe")
        assert f.costo_cop == 17500
        assert f.zona == "DEFAULT"

    def test_ciudad_vacia_usa_el_default(self, fletes):
        assert fletes.buscar(None).costo_cop == 17500

    def test_las_zonas_lejanas_tardan_mas(self, fletes):
        """Cuestan lo mismo —Lía cobra una tarifa nacional— pero el tiempo de
        transporte sí es distinto, y de eso depende lo que se le promete."""
        bogota, leticia = fletes.buscar("Bogotá"), fletes.buscar("Leticia")
        assert leticia.costo_cop == bogota.costo_cop == 17500
        assert leticia.dias_transporte > bogota.dias_transporte
