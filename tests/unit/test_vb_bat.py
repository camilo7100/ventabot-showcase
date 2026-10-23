"""El `.bat` es la única puerta de entrada al proyecto en Windows. Se vigila.

POR QUÉ EXISTE ESTE ARCHIVO
===========================
`vb lia` falló con «El sistema no encuentra la etiqueta por lotes
especificada». La causa: al agregar el comando, una sustitución de texto
buscó `:app` y encontró primero el `goto :app` de la tabla de despacho en vez
de la etiqueta `:app` del final. El reemplazo partió la tabla en dos y dejó
seis comandos inalcanzables.

Un `.bat` roto no lo detecta nada: no hay compilador, ni intérprete, ni
linter. Lo detecta el usuario, intentando trabajar. Estos tests convierten
eso en un fallo de CI.

Se comprueban tres cosas, y las tres han fallado alguna vez de verdad:
  1. Que todo `goto :X` tenga su etiqueta `:X`.
  2. Que cada script de `scripts/` sea alcanzable por algún comando.
  3. Que el archivo siga siendo válido para cmd.exe: CRLF y solo ASCII.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
VB = RAIZ / "vb.bat"

#: `goto :eof` es una etiqueta que cmd.exe define solo. No está en el archivo.
INTEGRADAS = {"eof"}

#: Scripts que no se exponen como comando a propósito.
SIN_COMANDO = {"__init__.py"}


@pytest.fixture(scope="module")
def texto() -> str:
    return VB.read_text(encoding="utf-8")


class TestEstructura:
    def test_todo_goto_tiene_su_etiqueta(self, texto):
        """El bug exacto que dejó `vb lia` sin destino."""
        gotos = set(re.findall(r"goto\s+:(\w[\w-]*)", texto)) - INTEGRADAS
        etiquetas = set(re.findall(r"^:(\w[\w-]*)", texto, re.MULTILINE))
        huerfanos = sorted(gotos - etiquetas)
        assert not huerfanos, (
            f"comandos que apuntan a una etiqueta inexistente: {huerfanos}. "
            f"En Windows fallan con «no encuentra la etiqueta por lotes»."
        )

    def test_toda_etiqueta_se_usa(self, texto):
        """Una etiqueta sin `goto` es código muerto: alguien la dejó suelta."""
        gotos = set(re.findall(r"goto\s+:(\w[\w-]*)", texto))
        etiquetas = set(re.findall(r"^:(\w[\w-]*)", texto, re.MULTILINE))
        assert not sorted(etiquetas - gotos)

    def test_la_tabla_de_despacho_no_esta_partida(self, texto):
        """Todos los `if` de despacho van seguidos, antes de la primera
        etiqueta. Si una etiqueta se cuela en medio, los comandos que quedan
        debajo son inalcanzables — y en silencio."""
        lineas = texto.splitlines()
        primera_etiqueta = next(
            i for i, línea in enumerate(lineas) if re.match(r"^:\w", línea)
        )
        despues = [
            (i, línea)
            for i, línea in enumerate(lineas)
            if i > primera_etiqueta and línea.startswith('if /I "%~1"==')
        ]
        assert not despues, (
            f"hay despacho DESPUÉS de la primera etiqueta (línea "
            f"{primera_etiqueta + 1}): esos comandos no se alcanzan nunca. "
            f"Primero: {despues[0]}"
        )

    def test_cada_comando_termina_su_bloque(self, texto):
        """Sin `goto :eof`, un comando sigue ejecutando el bloque siguiente:
        `vb lint` correría también los tests, y el usuario no sabría por qué."""
        bloques = re.split(r"^:(\w[\w-]*)", texto, flags=re.MULTILINE)[1:]
        pares = list(zip(bloques[::2], bloques[1::2], strict=True))
        for nombre, cuerpo in pares[:-1]:
            assert "goto :eof" in cuerpo, (
                f"el bloque :{nombre} no termina en `goto :eof` y se derrama "
                f"sobre el siguiente"
            )


class TestCobertura:
    def test_todo_script_es_alcanzable_desde_vb(self, texto):
        """Un script sin comando es un script que el usuario no va a usar."""
        scripts = {p.name for p in (RAIZ / "scripts").glob("*.py")} - SIN_COMANDO
        invocados = set(re.findall(r"scripts\\(\w+\.py)", texto))
        huerfanos = sorted(scripts - invocados)
        assert not huerfanos, f"scripts sin comando en vb.bat: {huerfanos}"

    def test_todo_script_invocado_existe(self, texto):
        """Un `vb` que llama a un archivo que no está falla con un error de
        Python incomprensible."""
        for nombre in set(re.findall(r"scripts\\(\w+\.py)", texto)):
            assert (RAIZ / "scripts" / nombre).exists(), f"vb llama a {nombre}"

    def test_todo_comando_aparece_en_la_ayuda(self, texto):
        """`vb` sin argumentos lista lo que se puede hacer. Un comando que no
        salga ahí, no existe para quien lo usa."""
        comandos = set(re.findall(r'if /I "%~1"=="([\w-]+)"', texto)) - {"help"}
        ayuda = set(re.findall(r"^echo\s+vb ([\w-]+)", texto, re.MULTILINE))
        sin_documentar = sorted(comandos - ayuda)
        assert not sin_documentar, f"comandos invisibles en `vb`: {sin_documentar}"


class TestCompatibilidadWindows:
    def test_usa_saltos_de_linea_CRLF(self):
        """cmd.exe puede comportarse de forma rarísima con un .bat en LF:
        etiquetas que no encuentra, argumentos que se pierden."""
        crudo = VB.read_bytes()
        solitarios = re.findall(rb"(?<!\r)\n", crudo)
        assert not solitarios, f"{len(solitarios)} saltos de línea sin CR"

    def test_es_solo_ASCII(self):
        """La consola de Windows arranca en cp1252. Una tilde o un ✔ dentro
        del .bat se ve como basura, o revienta el intérprete."""
        crudo = VB.read_bytes()
        malos = {
            (n, línea)
            for n, línea in enumerate(crudo.splitlines(), 1)
            if any(b > 127 for b in línea)
        }
        assert not malos, f"caracteres no ASCII en vb.bat: {sorted(malos)[:3]}"


class TestParidadConElMakefile:
    def test_el_Makefile_ofrece_los_mismos_comandos(self, texto):
        """Windows y Linux tienen que poder hacer lo mismo. Si divergen, la
        documentación miente para la mitad de la gente."""
        makefile = (RAIZ / "Makefile").read_text(encoding="utf-8")
        objetivos = set(re.findall(r"^([\w-]+):", makefile, re.MULTILINE))
        comandos = set(re.findall(r'if /I "%~1"=="([\w-]+)"', texto)) - {"help"}
        solo_en_windows = sorted(comandos - objetivos)
        assert not solo_en_windows, (
            f"comandos que existen en vb.bat pero no en el Makefile: {solo_en_windows}"
        )
