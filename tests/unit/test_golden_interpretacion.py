"""El golden dataset del contrato nuevo: su forma, y que el sistema lo mide bien.

Un dataset mal escrito da métricas mentirosas, y una métrica mentirosa es peor
que ninguna: se toman decisiones con ella. Estos tests vigilan el dataset, no
el modelo — al modelo lo mide `vb golden`, que necesita Ollama corriendo.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "scripts"))

from app.domain.acciones import Accion, planificar  # noqa: E402
from app.domain.interpretacion import (  # noqa: E402
    Acto,
    Atributo,
    Entidad,
    TipoReferencia,
)

DATASET = RAIZ / "tests" / "golden" / "interpretacion.csv"


@pytest.fixture(scope="module")
def filas():
    with DATASET.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestFormaDelDataset:
    def test_hay_suficientes_mensajes(self, filas):
        assert len(filas) >= 100, "menos de 100 ejemplos no mide nada"

    def test_todas_las_etiquetas_existen(self, filas):
        actos = {a.value for a in Acto}
        entidades = {e.value for e in Entidad}
        atributos = {a.value for a in Atributo}
        refs = {r.value for r in TipoReferencia}
        for f in filas:
            assert f["acto"] in actos, f["acto"]
            assert f["entidad"] in entidades, f["entidad"]
            assert f["atributo"] in atributos, f["atributo"]
            assert f["ref_tipo"] in refs, f["ref_tipo"]

    def test_no_hay_mensajes_repetidos(self, filas):
        vistos = [f["mensaje"].strip().lower() for f in filas]
        repes = {m for m in vistos if vistos.count(m) > 1}
        assert not repes, f"repetidos (inflan la métrica): {repes}"

    def test_el_ordinal_siempre_trae_su_numero(self, filas):
        for f in filas:
            if f["ref_tipo"] == "ORDINAL":
                assert f["ref_pos"], f"«{f['mensaje']}» es ordinal y no dice cuál"
            else:
                assert not f["ref_pos"]

    def test_cada_acto_tiene_al_menos_dos_ejemplos(self, filas):
        cuenta = Counter(f["acto"] for f in filas)
        flacos = {k: v for k, v in cuenta.items() if v < 2}
        assert not flacos, f"con un solo ejemplo no se mide nada: {flacos}"

    def test_estan_los_casos_de_referencia(self, filas):
        """Son la razón de ser del rediseño: si no se miden, no se sabe si
        funcionan."""
        tipos = {f["ref_tipo"] for f in filas}
        for imprescindible in ("ORDINAL", "ESE", "OTRO", "ULTIMO"):
            assert imprescindible in tipos, f"falta medir «{imprescindible}»"

    def test_se_miden_las_acciones_que_cuestan_dinero(self, filas):
        from app.domain.acciones import CRITICAS

        acciones = {
            planificar(Acto(f["acto"]), Entidad(f["entidad"]), Atributo(f["atributo"]))
            for f in filas
        }
        assert acciones & CRITICAS, "no hay ni un caso crítico en el dataset"


class TestLoQueNoPuedeFallarNunca:
    def test_ya_pague_esta_etiquetado_como_INFORMAR_y_no_CONFIRMAR(self, filas):
        """Si se etiquetara mal, el dataset estaría premiando el error más
        caro que puede cometer el sistema."""
        for f in filas:
            if "ya pague" in f["mensaje"].lower():
                assert f["acto"] == "INFORMAR"
                assert f["entidad"] == "PAGO"

    def test_ningun_pago_termina_en_una_accion_que_confirme(self, filas):
        for f in filas:
            if f["entidad"] == "PAGO" and f["acto"] in ("INFORMAR", "CONFIRMAR"):
                accion = planificar(
                    Acto(f["acto"]), Entidad(f["entidad"]), Atributo(f["atributo"])
                )
                assert accion is Accion.REGISTRAR_PAGO_REPORTADO

    def test_las_quejas_van_a_un_humano(self, filas):
        for f in filas:
            if f["acto"] == "HUMANO":
                accion = planificar(
                    Acto(f["acto"]), Entidad(f["entidad"]), Atributo(f["atributo"])
                )
                assert accion is Accion.LLAMAR_HUMANO


class TestElMedidor:
    """Que `vb golden` mida lo que dice medir."""

    def test_la_metrica_principal_es_la_ACCION_no_la_etiqueta(self):
        """Dos etiquetas distintas que llevan a la misma acción no son un
        fallo: la clienta recibe exactamente lo mismo."""
        import golden

        from app.domain.interpretacion import Interpretacion

        a = Interpretacion(
            acto=Acto.CONSULTAR, entidad=Entidad.PRODUCTO, atributo=Atributo.PRECIO
        )
        b = Interpretacion(acto=Acto.CONSULTAR, entidad=Entidad.PRODUCTO)
        resultado = golden.comparar(a, b)
        assert resultado["accion"] is True
        assert resultado["atributo"] is False, "el diagnóstico sí debe notarlo"

    def test_un_fallo_de_verdad_se_cuenta_como_fallo(self):
        import golden

        from app.domain.interpretacion import Interpretacion

        a = Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.PAGO)
        b = Interpretacion(acto=Acto.CONFIRMAR, entidad=Entidad.NINGUNA)
        assert golden.comparar(a, b)["accion"] is False

    def test_la_linea_base_apaga_el_modelo_de_verdad(self):
        """`--solo-python` tiene que medir solo los atajos y los parsers. Si
        se colara el modelo, la comparación no valdría nada."""
        import golden

        interprete, quien = golden.construir_interprete(solo_python=True)
        assert quien == "solo-python"
        with pytest.raises(RuntimeError, match="apagado"):
            interprete._llm.extract("", "", None)

    def test_el_dataset_entero_se_puede_convertir_sin_reventar(self, filas):
        import golden

        for f in filas:
            golden.Caso(**f).esperado()


class TestElPromptExiste:
    def test_esta_versionado_como_archivo(self):
        """Un prompt es código: se revisa en un pull request y se puede
        comparar entre versiones con el mismo dataset."""
        ruta = RAIZ / "app" / "prompts" / "interpretacion_v1.txt"
        assert ruta.exists()
        texto = ruta.read_text(encoding="utf-8")
        assert "{{CATALOGO}}" in texto, "no inyecta el catálogo real"
        assert len(texto) < 8000, "un prompt enorme no cabe en un modelo pequeño"

    def test_el_prompt_nombra_todos_los_actos(self):
        texto = (RAIZ / "app" / "prompts" / "interpretacion_v1.txt").read_text(
            encoding="utf-8"
        )
        faltan = [a.value for a in Acto if a.value not in texto]
        assert not faltan, f"el modelo no puede elegir lo que no le explicas: {faltan}"

    def test_el_prompt_prohibe_explicitamente_el_error_mas_caro(self):
        texto = (RAIZ / "app" / "prompts" / "interpretacion_v1.txt").read_text(
            encoding="utf-8"
        )
        assert "Nunca es CONFIRMAR" in texto


class TestLosGuardasDeSeguridad:
    """Reglas que NO se delegan a un modelo, y por qué.

    Cada una nació de un fallo real de granite 3B midiendo el dataset. No son
    parches: son decisiones sobre qué es demasiado caro para dejarlo al
    criterio de un clasificador probabilístico.
    """

    @pytest.fixture
    def interprete(self):
        from app.conversacion.interprete import Interprete

        class SinModelo:
            def extract(self, *a, **k):
                raise RuntimeError("apagado: aquí solo deben puntuar los guardas")

        return Interprete(SinModelo(), "")

    @pytest.fixture
    def vacio(self):
        from app.domain.contexto import ContextoConversacional

        return ContextoConversacional(conversation_id="t")

    @pytest.mark.parametrize(
        "queja",
        [
            "me llego partido",
            "se le cayo una piedra a la semana",
            "no me ha llegado y ya paso un mes",
            "quiero devolverlo",
            "me llego roto",
            "esto es una estafa",
        ],
    )
    def test_toda_queja_va_a_una_persona(self, interprete, vacio, queja):
        """El modelo leyó «me llegó partido» como INFORMAR y «se le cayó una
        piedra» como PREGUNTAR. Las dos habrían dejado a una clienta enfadada
        hablando con un bot."""
        from app.domain.acciones import Accion, planificar

        r = interprete.interpretar(queja, None, vacio)
        assert planificar(r.acto, r.entidad, r.atributo) is Accion.LLAMAR_HUMANO

    def test_una_PREGUNTA_sobre_pagos_no_es_un_pago(self, interprete, vacio):
        """El fallo más caro del lote: el modelo leyó «¿puedo pagar cuando lo
        reciba?» como INFORMAR·PAGO, y eso abre un caso de pago reportado por
        alguien que no ha pagado nada."""
        from app.domain.interpretacion import Acto, Entidad

        r = interprete.interpretar("puedo pagar cuando lo reciba", None, vacio)
        assert not (r.acto is Acto.INFORMAR and r.entidad is Entidad.PAGO)

    @pytest.mark.parametrize(
        "aviso", ["ya pague", "acabo de consignar", "ya hice la transferencia"]
    )
    def test_pero_decir_que_pago_si_se_registra(self, interprete, vacio, aviso):
        from app.domain.interpretacion import Acto, Entidad

        r = interprete.interpretar(aviso, None, vacio)
        assert r.acto is Acto.INFORMAR and r.entidad is Entidad.PAGO

    def test_un_numero_de_huellitas_NO_es_un_ordinal(self):
        """El modelo leyó el 2 de «el de 2 huellitas» como «el segundo
        pedido» y mandó la compra a consultar otra cosa. Python sabe que ahí
        no hay ningún ordinal, y ahora eso gana."""
        from app.conversacion.interprete import leer_referencia
        from app.domain.interpretacion import TipoReferencia

        assert leer_referencia("quiero el de 2 huellitas").tipo is (
            TipoReferencia.NINGUNA
        )

    def test_una_talla_inventada_por_el_modelo_se_borra(self, vacio):
        """«Continuemos» salía con talla 8. Un número está en la frase o no
        está: no es una interpretación."""
        from app.conversacion.interprete import Interprete
        from app.domain.interpretacion import (
            Acto,
            DatosSueltos,
            Interpretacion,
        )

        class ModeloQueAlucina:
            def extract(self, *a, **k):
                return Interpretacion(
                    acto=Acto.INFORMAR, datos=DatosSueltos(talla=8, huellitas=3)
                )

        r = Interprete(ModeloQueAlucina(), "").interpretar("me gusta mucho", None, vacio)
        assert r.datos.talla is None
        assert r.datos.huellitas is None


class TestLaTablaPerdonaAlModelo:
    """Un hecho del negocio se contesta igual lo pregunte quien lo pregunte.

    Exigirle al modelo que acierte el verbo Y el sustantivo Y el atributo
    multiplica por tres las formas de fallar sin ganar nada: la clienta recibe
    el mismo párrafo en todos los casos.
    """

    @pytest.mark.parametrize(
        ("acto", "entidad", "atributo", "esperada"),
        [
            ("PREGUNTAR", "NINGUNA", "MEDIOS_DE_PAGO", "EXPLICAR_COMO_PAGAR"),
            ("CONSULTAR", "PAGO", "MEDIOS_DE_PAGO", "EXPLICAR_COMO_PAGAR"),
            ("CONSULTAR", "ENVIO", "COSTO_ENVIO", "RESPONDER_DUDA"),
            ("PREGUNTAR", "PEDIDO", "GARANTIA", "RESPONDER_DUDA"),
            ("CONSULTAR", "ENVIO", "TIEMPO", "RESPONDER_DUDA"),
            ("PREGUNTAR", "TALLA", "NINGUNO", "EXPLICAR_COMO_MEDIR"),
            ("PREGUNTAR", "NINGUNA", "COMO_MEDIR", "EXPLICAR_COMO_MEDIR"),
        ],
    )
    def test_da_igual_como_lo_diga(self, acto, entidad, atributo, esperada):
        assert (
            planificar(Acto(acto), Entidad(entidad), Atributo(atributo)).value == esperada
        )

    def test_informar_algo_que_solo_sabemos_nosotros_es_consultarlo(self):
        """«Ya está listo mi anillo» suena a afirmación y es una pregunta."""
        for entidad, atributo in (("PEDIDO", "ESTADO"), ("PEDIDO", "SALDO")):
            assert (
                planificar(Acto.INFORMAR, Entidad(entidad), Atributo(atributo))
                is Accion.CONSULTAR_PEDIDO
            )
        assert (
            planificar(Acto.INFORMAR, Entidad.IMAGEN, Atributo.NINGUNO)
            is Accion.MOSTRAR_IMAGENES
        )

    def test_pero_cancelar_sigue_ganandole_a_todo(self):
        """La indulgencia con los hechos del negocio no puede tragarse una
        cancelación: «cancela el pedido, ¿cuánto era el envío?» tiene que
        seguir siendo una cancelación."""
        assert (
            planificar(Acto.CANCELAR, Entidad.PEDIDO, Atributo.COSTO_ENVIO)
            is Accion.PEDIR_CANCELACION
        )


class TestLatencia:
    def test_hay_un_techo_de_generacion(self):
        """Sin tope, medir dio 37 s en el peor caso: unos pocos mensajes
        hacían al modelo escribir hasta agotarse. Una clienta no espera 37
        segundos, se va — y la cola larga es la que decide si el bot se siente
        vivo, no la mediana."""
        from app.adapters.llm.ollama_client import OPCIONES_DETERMINISTAS

        assert OPCIONES_DETERMINISTAS["num_predict"] <= 512


class TestLasDosCorrecciones:
    """Gramática del negocio: verdades que el modelo no puede saber.

    Ninguna adivina. Las dos aplican algo que nosotros sabemos y él no, y son
    la diferencia entre exigirle a un modelo pequeño que acierte siempre y
    darle un sistema que aguanta cuando no acierta.
    """

    def _corregido(self, crudo, interp):
        from app.conversacion.interprete import _corregir

        r = _corregir(interp, crudo)
        return planificar(r.acto, r.entidad, r.atributo)

    def test_una_pregunta_sobre_pagos_NO_abre_un_caso_de_pago(self):
        from app.domain.interpretacion import Interpretacion

        accion = self._corregido(
            "puedo pagar cuando lo reciba",
            Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.PAGO),
        )
        assert accion is not Accion.REGISTRAR_PAGO_REPORTADO

    def test_pero_decir_que_ya_pago_si_lo_abre(self):
        from app.domain.interpretacion import Interpretacion

        accion = self._corregido(
            "ya pague", Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.PAGO)
        )
        assert accion is Accion.REGISTRAR_PAGO_REPORTADO

    @pytest.mark.parametrize(
        ("crudo", "acto", "ref"),
        [
            ("como va ese", "INFORMAR", "ESE"),
            ("el anterior como va", "CONVERSAR", "OTRO"),
            ("el ultimo que pedi", "INFORMAR", "ULTIMO"),
            ("y el otro?", "OTRO", "OTRO"),
        ],
    )
    def test_señalar_algo_sin_dar_un_dato_es_preguntar_por_ello(self, crudo, acto, ref):
        """El modelo dijo INFORMAR o CONVERSAR y acertó la referencia. Nadie
        «informa» sobre un pedido que señala y sobre el que no aporta nada."""
        from app.domain.interpretacion import (
            Interpretacion,
            Referencia,
            TipoReferencia,
        )

        accion = self._corregido(
            crudo,
            Interpretacion(
                acto=Acto(acto), referencia=Referencia(tipo=TipoReferencia(ref))
            ),
        )
        assert accion is Accion.CONSULTAR_PEDIDO

    def test_pero_señalar_algo_Y_DAR_un_dato_sigue_siendo_informar(self):
        """«Talla 8 para el segundo» tiene referencia Y dato: es informar, y
        convertirlo en consulta perdería la talla."""
        from app.domain.interpretacion import (
            DatosSueltos,
            Interpretacion,
            Referencia,
            TipoReferencia,
        )

        accion = self._corregido(
            "talla 8 para el segundo",
            Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.TALLA,
                referencia=Referencia(tipo=TipoReferencia.ORDINAL, posicion=2),
                datos=DatosSueltos(talla=8),
            ),
        )
        assert accion is Accion.ANOTAR_DATOS


class TestLaReglaQueSeMordioLaCola:
    """El caso más instructivo de toda la medición.

    La regla de «un hecho del negocio se contesta igual» arregló once fallos
    y creó cuatro nuevos: el modelo etiquetaba «corazón rojo dedos blancos»
    con el atributo COLOR_DISPONIBLE, y el bot contestaba el párrafo de «no
    manejamos dorado» en vez de anotar los colores.

    La salvedad es de principio, no un parche: una respuesta de FAQ nunca
    necesita un color ni una talla. Si vienen datos, la clienta está DANDO
    información, no pidiéndola.
    """

    @pytest.mark.parametrize(
        "mensaje",
        [
            "corazon rojo dedos blancos",
            "la quiero toda negra",
            "el corazon rosado y alrededor fucsia",
        ],
    )
    def test_dar_colores_no_se_confunde_con_preguntar_por_ellos(self, mensaje):
        accion = planificar(
            Acto.INFORMAR,
            Entidad.COLOR,
            Atributo.COLOR_DISPONIBLE,
            trae_datos=True,
        )
        assert accion is Accion.ANOTAR_DATOS

    def test_pero_preguntar_por_ellos_sigue_respondiendo_la_duda(self):
        accion = planificar(
            Acto.PREGUNTAR,
            Entidad.COLOR,
            Atributo.COLOR_DISPONIBLE,
            trae_datos=False,
        )
        assert accion is Accion.RESPONDER_DUDA


class TestElGrabado:
    """Nadie extraía los nombres. Ni el modelo ni Python.

    Aunque el modelo hubiera acertado el acto, el nombre se habría perdido
    igual — y es el dato que se graba en plata y no se deshace.
    """

    @pytest.mark.parametrize(
        ("mensaje", "esperado"),
        [
            ("Nombre rocky", ["rocky"]),
            ("que diga Luna y Simba", ["Luna", "Simba"]),
            ("el grabado seria Michi", ["Michi"]),
            ("se llama Pelusa", ["Pelusa"]),
            ("que lleve Max, Nina y Toby", ["Max", "Nina", "Toby"]),
            ("nombres: Coco y Lulu", ["Coco", "Lulu"]),
            ("quiero grabar el nombre de mi perro Rocky", ["Rocky"]),
        ],
    )
    def test_los_saca_de_como_escribe_la_gente(self, mensaje, esperado):
        from app.conversacion.interprete import leer_grabado

        assert leer_grabado(mensaje)[0] == esperado

    def test_respeta_la_mayuscula_como_la_escribio(self):
        """Se graba en plata: ella sabe cómo se escribe el nombre de su
        mascota mejor que nosotros."""
        from app.conversacion.interprete import leer_grabado

        assert leer_grabado("que diga MAX")[0] == ["MAX"]

    def test_no_quiere_grabado_es_una_respuesta(self):
        from app.conversacion.interprete import leer_grabado

        assert leer_grabado("sin grabado gracias") == ([], True)

    def test_no_inventa_nombres_donde_no_los_hay(self):
        from app.conversacion.interprete import leer_grabado

        for m in ("quiero un anillo de dos huellitas", "hola", "cuanto vale"):
            assert leer_grabado(m) == ([], False)

    def test_nunca_devuelve_mas_de_cinco(self):
        from app.conversacion.interprete import leer_grabado
        from app.domain.personalizacion import MAX_GRABADOS

        nombres = leer_grabado("que diga Ana, Beto, Caro, Dani, Eli, Fabi, Gabi")[0]
        assert len(nombres) <= MAX_GRABADOS


class TestLasPistasDeAtributo:
    """Rellenan el hueco, nunca pisan al modelo.

    «Tienen nequi» no necesita comprensión del lenguaje: necesita saber que
    Nequi es un medio de pago, y eso lo sabemos nosotros.
    """

    def _corregido(self, crudo, interp):
        from app.conversacion.interprete import _corregir

        return _corregir(interp, crudo)

    @pytest.mark.parametrize(
        ("mensaje", "atributo"),
        [
            ("tienen nequi", "MEDIOS_DE_PAGO"),
            ("aceptan daviplata", "MEDIOS_DE_PAGO"),
            ("no tengo regla como hago", "COMO_MEDIR"),
            ("y la garantia?", "GARANTIA"),
            ("cuanto se demora", "TIEMPO"),
            ("lo tienen en oro", "COLOR_DISPONIBLE"),
        ],
    )
    def test_completan_lo_que_el_modelo_dejo_vacio(self, mensaje, atributo):
        from app.domain.interpretacion import Interpretacion

        r = self._corregido(mensaje, Interpretacion(acto=Acto.PREGUNTAR))
        assert r.atributo is Atributo(atributo)

    def test_NO_pisan_lo_que_el_modelo_ya_eligio(self):
        """Si él eligió uno, sabe algo del contexto que una lista de palabras
        sueltas no."""
        from app.domain.interpretacion import Interpretacion

        r = self._corregido(
            "cuanto cuesta el envio",
            Interpretacion(acto=Acto.PREGUNTAR, atributo=Atributo.GARANTIA),
        )
        assert r.atributo is Atributo.GARANTIA

    def test_NO_se_aplican_si_el_mensaje_trae_datos(self):
        """«Que sea plata talla 8» no es una pregunta sobre el material."""
        from app.domain.interpretacion import DatosSueltos, Interpretacion

        r = self._corregido(
            "que sea de plata talla 8",
            Interpretacion(acto=Acto.INFORMAR, datos=DatosSueltos(talla=8)),
        )
        assert r.atributo is Atributo.NINGUNO


class TestPreguntarPorElEstadoNoEsConfirmar:
    def test_ya_esta_listo_mi_anillo_no_muestra_el_cobro(self):
        """El modelo lo leyó como CONFIRMAR, y eso le habría mostrado la
        pantalla de cobro a alguien que solo preguntaba."""
        from app.conversacion.interprete import _corregir
        from app.domain.interpretacion import Interpretacion

        r = _corregir(
            Interpretacion(acto=Acto.CONFIRMAR, entidad=Entidad.PEDIDO),
            "ya esta listo mi anillo",
        )
        accion = planificar(r.acto, r.entidad, r.atributo)
        assert accion is Accion.CONSULTAR_PEDIDO
        assert accion is not Accion.RESUMIR_Y_COBRAR_ABONO

    def test_pero_confirmar_de_verdad_sigue_cobrando(self):
        from app.conversacion.interprete import _corregir
        from app.domain.interpretacion import Interpretacion

        r = _corregir(Interpretacion(acto=Acto.CONFIRMAR), "listo confirmo")
        assert planificar(r.acto, r.entidad, r.atributo) is (
            Accion.RESUMIR_Y_COBRAR_ABONO
        )


class TestDarNombresEsDarElGrabado:
    def _accion(self, crudo, interp):
        from app.conversacion.interprete import _corregir

        r = _corregir(interp, crudo)
        return planificar(r.acto, r.entidad, r.atributo, trae_datos=r.datos.hay_algo())

    @pytest.mark.parametrize(
        ("mensaje", "acto_del_modelo"),
        [("Nombre rocky", "PREGUNTAR"), ("que diga Luna y Simba", "CONVERSAR")],
    )
    def test_aunque_el_modelo_no_entienda_la_frase(self, mensaje, acto_del_modelo):
        """Python sacó los nombres, así que el dato es un hecho. El modelo
        acertó que no era una compra y se perdió todo lo demás."""
        from app.conversacion.interprete import leer_grabado
        from app.domain.interpretacion import DatosSueltos, Interpretacion

        nombres, _ = leer_grabado(mensaje)
        accion = self._accion(
            mensaje,
            Interpretacion(
                acto=Acto(acto_del_modelo), datos=DatosSueltos(nombres=nombres)
            ),
        )
        assert accion is Accion.ANOTAR_DATOS

    def test_pero_una_compra_con_nombre_sigue_siendo_una_compra(self):
        """«Quiero un anillo que diga Rocky»: manda lo que pide, y el nombre
        viaja de paso."""
        from app.domain.interpretacion import DatosSueltos, Interpretacion

        accion = self._accion(
            "quiero un anillo que diga Rocky",
            Interpretacion(
                acto=Acto.COMPRAR,
                entidad=Entidad.PRODUCTO,
                datos=DatosSueltos(nombres=["Rocky"]),
            ),
        )
        assert accion is Accion.INICIAR_COMPRA
