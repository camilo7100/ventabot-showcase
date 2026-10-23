"""Que las piezas nuevas no se conviertan en la máquina rígida de antes.

Estos tests no prueban comportamiento: prueban que la ARQUITECTURA siga
siendo la que se decidió. Son los que se ponen rojos cuando alguien, con toda
la buena intención, empieza a arreglar un caso concreto metiendo un `if` en
el sitio equivocado.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from app.domain import acciones, contexto, hechos, interpretacion, referencias
from app.domain.acciones import CRITICAS, NECESITA, SOLO_LEEN, Accion, planificar
from app.domain.interpretacion import Acto, Atributo, Entidad

RAIZ = Path(__file__).resolve().parents[2]


class TestElContratoDelModelo:
    def test_la_interpretacion_NO_contiene_decisiones(self):
        """El modelo describe lo que oyó. Qué se hace lo decide la tabla.

        Si algún día aparece aquí un campo «accion» o «siguiente_paso», el
        modelo habrá vuelto a mandar sobre el negocio."""
        campos = set(interpretacion.Interpretacion.model_fields)
        prohibidos = {"accion", "paso", "nodo", "destino", "siguiente", "herramienta"}
        assert not (campos & prohibidos), (
            f"el modelo está decidiendo: {campos & prohibidos}"
        )

    def test_todos_los_campos_de_control_son_cerrados(self):
        """Un `str` libre en un campo de control reabre la puerta al caos."""
        from enum import Enum

        for nombre in ("acto", "entidad", "atributo"):
            anotacion = interpretacion.Interpretacion.model_fields[nombre].annotation
            assert issubclass(anotacion, Enum), f"{nombre} no es un Enum cerrado"

    def test_los_actos_no_se_han_multiplicado(self):
        """La lista de verbos NO debe crecer. Cuando parece que falta uno,
        casi siempre falta una Entidad o un Atributo — y ahí sí es barato."""
        assert len(list(Acto)) <= 15, (
            "los actos están creciendo: eso es la explosión de intenciones "
            "volviendo por la puerta de atrás"
        )

    def test_los_colores_siguen_siendo_del_muestrario(self):
        from app.domain.personalizacion import ColorCircon

        campo = interpretacion.DatosSueltos.model_fields["color_corazon"]
        assert ColorCircon in getattr(campo.annotation, "__args__", (campo.annotation,))


class TestLaTablaDeAcciones:
    def test_NO_existe_una_accion_que_confirme_un_pago(self):
        """Que la clienta diga «ya pagué» no puede mover un peso. Lo más lejos
        que llega el sistema es abrir un caso y pedir el comprobante."""
        nombres = {a.value for a in Accion}
        for prohibida in ("CONFIRMAR_PAGO", "APROBAR_PAGO", "MARCAR_PAGADO"):
            assert prohibida not in nombres

    def test_NO_existe_una_accion_que_cancele_sola(self):
        """Cancelar es un anillo de plata ya fundido. Lo decide una persona."""
        assert "CANCELAR_PEDIDO" not in {a.value for a in Accion}
        assert Accion.PEDIR_CANCELACION in CRITICAS

    def test_toda_accion_del_enum_es_alcanzable_o_esta_justificada(self):
        """Una acción inalcanzable es código que nunca corre y que nadie sabe
        que no corre."""
        alcanzables = acciones.acciones_alcanzables()
        # Estas se alcanzan desde el ejecutor o el redactor, no desde la tabla.
        indirectas = {
            Accion.PEDIR_LO_QUE_FALTA,
            Accion.RECIBIR_COMPROBANTE,
            Accion.PEDIR_COMPROBANTE,
            Accion.LISTAR_PEDIDOS,
        }
        huerfanas = set(Accion) - alcanzables - indirectas
        assert not huerfanas, f"acciones a las que nunca se llega: {huerfanas}"

    def test_lo_que_cuesta_dinero_esta_marcado_como_critico(self):
        for accion in (
            Accion.REGISTRAR_PAGO_REPORTADO,
            Accion.PEDIR_CANCELACION,
            Accion.RESUMIR_Y_COBRAR_ABONO,
        ):
            assert accion in CRITICAS

    def test_ninguna_accion_critica_esta_en_las_que_solo_leen(self):
        assert not (CRITICAS & SOLO_LEEN)

    def test_toda_accion_critica_necesita_saber_sobre_QUE_actua(self):
        """Una acción cara sin objetivo definido es una acción cara sobre el
        pedido equivocado."""
        from app.domain.acciones import Requisito

        for accion in CRITICAS:
            requisitos = NECESITA.get(accion, ())
            assert requisitos, f"{accion.value} es crítica y no exige nada"
            assert Requisito.PEDIDO in requisitos or Requisito.PROCESO in requisitos

    def test_lo_desconocido_cae_en_no_entendi_y_no_en_algo_caro(self):
        """El default de la tabla no puede ser una acción que escriba."""
        assert planificar(Acto.OTRO, Entidad.NINGUNA, Atributo.NINGUNO) is (
            Accion.NO_ENTENDI
        )
        assert Accion.NO_ENTENDI in SOLO_LEEN


class TestNoHayMaquinaDeEstadosNueva:
    def test_no_existe_un_orden_fijo_de_preguntas(self):
        """El defecto que este rediseño vino a quitar. Si vuelve a aparecer un
        `ORDEN` recorrido en secuencia, volvimos al paso 1, paso 2."""
        for modulo in (contexto, referencias, acciones):
            fuente = inspect.getsource(modulo)
            assert not re.search(r"^ORDEN\b", fuente, re.MULTILINE), (
                f"{modulo.__name__} tiene un ORDEN: la máquina rígida está volviendo"
            )

    def test_el_contexto_admite_VARIOS_procesos(self):
        campo = contexto.ContextoConversacional.model_fields["procesos"]
        assert "list" in str(campo.annotation), (
            "los procesos volvieron a ser uno solo: la interrupción deja de "
            "ser representable"
        )

    def test_el_proceso_guarda_lo_que_FALTA_no_en_que_paso_va(self):
        campos = set(contexto.Proceso.model_fields)
        assert "faltan" in campos
        assert "paso" not in campos and "etapa" not in campos


class TestLaSalidaEstaEncerrada:
    def test_el_validador_de_hechos_bloquea_una_cifra_inventada(self):
        ficha = hechos.Ficha(montos=["$140.000"])
        assert not hechos.revisar("Tu saldo es de $180.000", ficha).aprobado
        assert hechos.revisar("Tu saldo es de $140.000", ficha).aprobado

    def test_bloquea_promesas_que_nadie_autorizo(self):
        for promesa in ("Te hago un descuento", "El envío es gratis"):
            assert not hechos.revisar(promesa, hechos.Ficha()).aprobado

    def test_sin_modelo_la_redaccion_libre_esta_APAGADA(self):
        """Es el valor por defecto y tiene que seguir siéndolo: la fase que
        puede decir algo falso no se enciende por descuido."""
        from app.conversacion.redactor import Redactor

        assert Redactor()._libre is False
        assert Redactor(llm=object())._libre is False, (
            "se encendió solo por tener un modelo"
        )


class TestLaPuertaAlBotPropositivo:
    def test_el_pipeline_se_puede_arrancar_sin_mensaje(self):
        from app.conversacion.pipeline import Pipeline

        firma = inspect.signature(Pipeline.desde_accion)
        assert "accion" in firma.parameters
        assert "texto" not in firma.parameters, (
            "el camino propositivo depende de un mensaje entrante: entonces no "
            "es propositivo"
        )

    def test_el_contexto_se_puede_consultar_desde_fuera_de_la_conversacion(self):
        """Un checkpoint solo se lee desde dentro de su conversación. Un
        recordatorio necesita preguntar por TODAS a la vez."""
        from app.adapters.repositories.sqlite_store import SqliteContexto

        assert hasattr(SqliteContexto, "con_procesos_abiertos")


class TestSinBotones:
    def test_ningun_texto_del_redactor_dice_selecciona_o_presiona(self):
        from app.conversacion import redactor

        fuente = inspect.getsource(redactor)
        for feo in ("Seleccione", "Presione", "Elija una opción", "Proceso completado"):
            assert feo not in fuente

    def test_las_piezas_no_llevan_opciones_por_defecto(self):
        from app.domain.respuesta import Respuesta

        r = Respuesta().decir("hola")
        assert r.piezas[0].opciones == ()


@pytest.mark.parametrize(
    "modulo",
    [interpretacion, contexto, referencias, acciones, hechos],
)
def test_el_dominio_nuevo_no_importa_nada_de_afuera(modulo):
    """La regla que permite cambiar de modelo, de base de datos y de canal."""
    fuente = Path(modulo.__file__).read_text(encoding="utf-8")
    prohibido = re.compile(
        r"^\s*(from|import)\s+app\.(adapters|graph|api|infra|workers|conversacion)\b",
        re.MULTILINE,
    )
    assert not prohibido.findall(fuente)
