"""Enseñarle a la clienta cómo le va a quedar su huellita, antes de fabricarla.

════════════════════════════════════════════════════════════════════════════
POR QUÉ ESTO VENDE
════════════════════════════════════════════════════════════════════════════
Escoger dos colores de una lista de catorce, sobre una foto de bolsitas, es
pedirle a alguien que imagine una joya. La mitad no se decide, y de esa mitad
una parte se va.

Enseñarle SU anillo —el corazón rojo, los deditos azules, en la foto de
verdad— convierte una decisión abstracta en un «¡ay, sí!». Es la misma foto
que le mandaría Lía si tuviera tiempo de fotografiar cada combinación.

════════════════════════════════════════════════════════════════════════════
CÓMO SE HACE, Y POR QUÉ NO HACE FALTA OPENCV
════════════════════════════════════════════════════════════════════════════
Hay UNA foto base: la huellita en circón transparente sobre fondo blanco. Las
cinco piedras están SIEMPRE en el mismo sitio, así que dónde está cada una se
calculó una vez y vive en `huellita_mascaras.png` (5,6 KB). En caliente solo
queda teñir, que son cuatro operaciones de numpy.

Detectar las piedras en cada mensaje habría sido volver a resolver un
problema ya resuelto, en el peor momento (mientras la clienta espera) y con
una dependencia de cuarenta megas.

════════════════════════════════════════════════════════════════════════════
TEÑIR SIN MATAR EL BRILLO
════════════════════════════════════════════════════════════════════════════
Un circón no es un círculo de color: es un montón de facetas con reflejos
blancos y sombras. Si se pinta encima, queda un sticker.

Por eso de la foto se toman solo las FACETAS (qué tan clara es cada parte de
la piedra) y el color lo pone el panel: la piedra da, en promedio, el color
exacto que se escogió, más clara o más oscura según su faceta, y los reflejos
más fuertes se van hacia blanco, que es el chispazo que la hace bonita. Cuánto
se marcan las facetas y cuánto brillan los reflejos también se mueve en el
panel (Colores), bolsita por bolsita, mirando el dibujo en vivo (`Acabado`).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.domain.personalizacion import (
    ACABADO_COLOR,
    HEX_COLOR,
    Acabado,
    ColorCircon,
    Huellita,
)

log = logging.getLogger("ventabot.render")

#: Qué huellitas van volteadas, contando desde 0. Solo la segunda: en el
#: anillo de dos, una mira arriba y la otra abajo; en el de tres, la del medio
#: es la que va al revés. Es el diseño del anillo, no una opción.
VUELTAS = frozenset({1})

#: Cómo se pinta cada piedra (`_tenir`), 30/09: el color promedio de la piedra
#: es EXACTAMENTE el del panel; la foto pone solo la textura de las facetas.
#: Facetas, reflejos y fuego son de cada bolsita (`Acabado`, panel → Colores).
#:
#: Facetas = 100 equivale a este contraste (cuánto se oscurecen y aclaran las
#: facetas alrededor del color; 50, el de fábrica, es la mitad).
CONTRASTE_MAXIMO = 3.2
#: Vueltas de corrección hasta que el promedio da el color escogido.
VUELTAS_DE_AJUSTE = 6
#: Cambia cuando cambia la manera de dibujar: las imágenes ya guardadas con el
#: dibujo viejo no se reusan (van en el nombre del archivo).
VERSION_DEL_DIBUJO = 3
#: Cuánto se difumina el borde de la silueta (px de la foto base).
SUAVE_DEL_BORDE = 1.2
#: El lado más largo de la foto del corazón que se manda (px).
LADO_DEL_CORAZON = 1080


def _hex_a_rgb(codigo: str) -> tuple[int, int, int]:
    codigo = codigo.lstrip("#")
    return tuple(int(codigo[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


#: Lo que se está PROBANDO en el panel y aún no se guardó: color y acabado por
#: bolsita. Lo que no venga aquí se dibuja con lo guardado (la paleta).
Tintes = dict[ColorCircon, str]
Acabados = dict[ColorCircon, Acabado]


class RenderDeHuellitas:
    """Genera la previsualización. Guarda en disco y no repite trabajo.

    El nombre del archivo sale de los colores, así que la misma combinación
    da siempre el mismo archivo: la segunda clienta que pida corazón rojo con
    deditos azules no gasta ni un milisegundo.
    """

    def __init__(self, base: Path, mascaras: Path, destino: Path) -> None:
        self._base = base
        self._mascaras = mascaras
        self._destino = destino
        self._cache: tuple | None = None

    # -- puerto -------------------------------------------------------------

    def previsualizar(
        self,
        huellitas: list[Huellita],
        tintes: Tintes | None = None,
        acabados: Acabados | None = None,
    ) -> str | None:
        """Dibuja las huellitas y devuelve el NOMBRE LÓGICO de la imagen.

        Devuelve None si algo falla. Una previsualización es un regalo, no un
        requisito: si no sale, la conversación sigue igual de bien y nadie se
        entera.
        """
        if not huellitas:
            return None
        nombre = self.nombre_de(huellitas, tintes, acabados)
        salida = self._destino / f"{nombre}.jpg"
        if salida.is_file():
            return nombre
        try:
            imagen = self.dibujar(huellitas, tintes, acabados)
        except Exception as exc:
            log.warning("no se pudo dibujar la previsualización (%s)", exc)
            return None
        self._destino.mkdir(parents=True, exist_ok=True)
        imagen.save(salida, format="JPEG", quality=88, optimize=True)
        log.info("previsualización nueva: %s", salida.name)
        return nombre

    def dibujar(
        self,
        huellitas: list[Huellita],
        tintes: Tintes | None = None,
        acabados: Acabados | None = None,
    ):
        """La imagen (PIL) SIN guardarla. El panel la pide en cada cambio de un
        número mientras se prueba: guardar cada prueba sería llenar el disco."""
        from PIL import Image

        patitas = [self._una(h, tintes or {}, acabados or {}) for h in huellitas]
        if len(patitas) == 1:
            return _recortar(patitas[0])

        # Varias huellitas: en fila, como van en el anillo, y la SEGUNDA
        # volteada. En el de dos, una mira arriba y otra abajo; en el de tres,
        # la de la mitad es la que va al revés. Así es el diseño y no admite
        # variaciones (Camilo, 20/09, con las fotos del anillo de verdad).
        recortadas = [
            _voltear(_recortar(p)) if i in VUELTAS else _recortar(p)
            for i, p in enumerate(patitas)
        ]
        alto = max(p.height for p in recortadas)
        hueco = alto // 12
        ancho = sum(p.width for p in recortadas) + hueco * (len(recortadas) - 1)
        lienzo = Image.new("RGB", (ancho, alto), "white")
        x = 0
        for patita in recortadas:
            lienzo.paste(patita, (x, (alto - patita.height) // 2))
            x += patita.width + hueco
        return lienzo

    # -- el anillo de corazón (17/10) ----------------------------------------

    def previsualizar_corazon(
        self,
        color: ColorCircon,
        tintes: Tintes | None = None,
        acabados: Acabados | None = None,
    ) -> str | None:
        """Cómo queda el anillo de corazón: SOLO el corazón, al derecho, de su
        color (Camilo, 17/10: «al igual que en las huellitas… esta vez solo el
        corazón al derecho»). Mismo contrato que `previsualizar`."""
        a = (acabados or {}).get(color, ACABADO_COLOR[color])
        tinte = (tintes or {}).get(color, HEX_COLOR[color])
        firma = (
            f"v{VERSION_DEL_DIBUJO}|corazon4|{color.value}:"
            f"{tinte}/{a.facetas}/{a.destellos}/{a.fuego}"
        )
        nombre = (
            "corazon_"
            + hashlib.sha1(firma.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
        )
        salida = self._destino / f"{nombre}.jpg"
        if salida.is_file():
            return nombre
        try:
            imagen = self.dibujar_corazon(color, tintes, acabados)
        except Exception as exc:
            log.warning("no se pudo dibujar el corazón (%s)", exc)
            return None
        self._destino.mkdir(parents=True, exist_ok=True)
        # Calidad (Camilo, 17/10: «la veo de baja calidad»): la piedra de la
        # foto base mide ~500 px. Se agranda con LANCZOS y se guarda sin
        # submuestreo de color: con 4:2:0, el borde de un fucsia o un azul rey
        # sale en cuadritos.
        imagen = _agrandar(imagen, LADO_DEL_CORAZON)
        imagen.save(salida, format="JPEG", quality=95, subsampling=0, optimize=True)
        log.info("previsualización nueva del corazón: %s", salida.name)
        return nombre

    def dibujar_corazon(
        self,
        color: ColorCircon,
        tintes: Tintes | None = None,
        acabados: Acabados | None = None,
    ):
        """La piedra grande de la foto base (la máscara 1), teñida y volteada:
        en la huellita el corazón va con la punta arriba; en el anillo de
        corazón, al derecho (la punta abajo).

        En la foto, el dedito de la derecha le tapa un pedazo al corazón. Como
        el corazón es simétrico, se arma con su mitad IZQUIERDA (limpia) y esa
        misma mitad en espejo. Sin deditos, sin parches."""
        import numpy as np
        from PIL import Image, ImageFilter

        base, mascaras = self._cargar()
        piedra = mascaras == 1
        xs = np.nonzero(piedra.any(axis=0))[0]
        desde, mitad = int(xs[0]), (int(xs[0]) + int(xs[-1]) + 1) // 2
        izquierda, forma = base[:, desde:mitad], piedra[:, desde:mitad]
        pixeles = np.concatenate([izquierda, izquierda[:, ::-1]], axis=1)
        zona = np.concatenate([forma, forma[:, ::-1]], axis=1)
        pixeles[zona] = _tenir(
            pixeles[zona],
            (tintes or {}).get(color, HEX_COLOR[color]),
            (acabados or {}).get(color, ACABADO_COLOR[color]),
        )
        # Fuera del corazón, blanco; el borde suavizado para que no salga en
        # escalones.
        alfa = Image.fromarray(zona.astype(np.uint8) * 255).filter(
            ImageFilter.GaussianBlur(SUAVE_DEL_BORDE)
        )
        a = (np.asarray(alfa).astype(np.float32) / 255)[..., None]
        pixeles = pixeles * a + (1 - a)
        imagen = Image.fromarray((np.clip(pixeles, 0, 1) * 255).astype(np.uint8))
        return _recortar(_voltear(imagen))

    @staticmethod
    def nombre_de(
        huellitas: list[Huellita],
        tintes: Tintes | None = None,
        acabados: Acabados | None = None,
    ) -> str:
        """Un nombre estable y corto para esta combinación exacta.

        Lleva también el tinte (`HEX_COLOR`) y el acabado de cada color usado,
        y la versión del dibujo: las imágenes se guardan y se reusan, y sin
        esto, al cambiar un color en el panel, el servidor seguiría mandando
        las dibujadas antes. Las ya enviadas siguen existiendo con su nombre.
        """

        def de(c: ColorCircon) -> str:
            a = (acabados or {}).get(c, ACABADO_COLOR[c])
            tinte = (tintes or {}).get(c, HEX_COLOR[c])
            return f"{tinte}/{a.facetas}/{a.destellos}/{a.fuego}"

        firma = f"v{VERSION_DEL_DIBUJO}|" + "|".join(
            h.corazon.value
            + "-"
            + "-".join(c.value for c in h.colores_de_los_dedos)
            + ":"
            + ",".join(de(c) for c in (h.corazon, *h.colores_de_los_dedos))
            for h in huellitas
        )
        return (
            "vista_"
            + hashlib.sha1(firma.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
        )

    # -- dibujo -------------------------------------------------------------

    def _cargar(self):
        if self._cache is None:
            import numpy as np
            from PIL import Image

            base = Image.open(self._base).convert("RGB")
            mascaras = Image.open(self._mascaras).convert("L")
            if mascaras.size != base.size:
                mascaras = mascaras.resize(base.size, Image.NEAREST)
            pixeles = np.asarray(base).astype(np.float32) / 255.0
            self._cache = (pixeles, np.asarray(mascaras))
        return self._cache

    def _una(self, huellita: Huellita, tintes: Tintes, acabados: Acabados):
        import numpy as np
        from PIL import Image

        base, mascaras = self._cargar()
        pixeles = base.copy()

        # El corazón es la máscara 1; los deditos, de la 2 a la 5, y están
        # numerados de izquierda a derecha (x = 292, 434, 643, 785 en la foto
        # base). Cada uno lleva SU color: una clienta puede pedirlos alternos.
        piedras = zip(
            (1, 2, 3, 4, 5),
            (huellita.corazon, *huellita.colores_de_los_dedos),
            strict=True,
        )
        for valor, color in piedras:
            zona = mascaras == valor
            if zona.any():
                pixeles[zona] = _tenir(
                    pixeles[zona],
                    tintes.get(color, HEX_COLOR[color]),
                    acabados.get(color, ACABADO_COLOR[color]),
                )
        return Image.fromarray((np.clip(pixeles, 0, 1) * 255).astype(np.uint8))


def _agrandar(imagen, lado: int):
    """Hasta `lado` px en su lado más largo, con LANCZOS y un toque de nitidez
    (agrandar suaviza). Nunca la achica."""
    from PIL import Image, ImageFilter

    escala = lado / max(imagen.size)
    if escala <= 1:
        return imagen
    grande = imagen.resize(
        (round(imagen.width * escala), round(imagen.height * escala)), Image.LANCZOS
    )
    return grande.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))


def _voltear(imagen):
    """La misma huellita mirando al otro lado."""
    from PIL import Image

    return imagen.transpose(Image.FLIP_TOP_BOTTOM)


def _tenir(foto, tinte: str, acabado: Acabado):
    """Los píxeles de UNA piedra (Nx3), pintados del color EXACTO del panel
    con las facetas de la foto.

    30/09, Camilo: «al dar Ver sí cambia el color, pero no necesariamente al
    que coloco». Antes se tomaban solo el tono y la saturación (el brillo se
    ignoraba), la saturación se apagaba donde la foto es clara —y la foto base
    es un diamante blanco, clara casi toda— y el blanco y el negro ni miraban
    el color. Ahora:

    1. Las facetas de la foto dan solo la TEXTURA: cada píxel es el color
       escogido, más claro o más oscuro según su faceta (`acabado.facetas`),
       y con el arcoíris del diamante si se pide (`acabado.fuego`).
    2. Se CORRIGE en vueltas hasta que el color promedio del CUERPO de la
       piedra es el del panel, canal por canal. Lo que se ve es lo que se
       escogió.
    3. Encima, las facetas de luz reciben luz blanca (`acabado.destellos`),
       como en una piedra de verdad: el reflejo es luz, no color. Por eso el
       promedio se mide sin ese blanco: si se midiera con él, la corrección
       volvería a teñir de color el reflejo y el número no se notaría.
    """
    import numpy as np

    objetivo = np.array(_hex_a_rgb(tinte), dtype=np.float32) / 255
    contraste = CONTRASTE_MAXIMO * acabado.facetas / 100
    fuerza = acabado.destellos / 100

    brillo = foto.max(axis=1)  # las facetas (el V de HSV)
    relativo = (brillo / max(float(brillo.mean()), 1e-3)) ** contraste
    # Dos texturas, mezcladas por el FUEGO: la de la luz sola (gris: la piedra
    # es solo de su color) y la de la foto canal por canal, que trae el
    # arcoíris del diamante. Con fuego 100, el color promedio de la foto y
    # facetas 31 (contraste 1), la piedra ES la foto: así queda el blanco de
    # fábrica (Camilo, 30/09: «estaba mejor antes»). En los colores, ese
    # arcoíris salía como rayas verdes en el amarillo: de fábrica, fuego 0.
    fuego = acabado.fuego / 100
    textura = relativo[:, None]
    if fuego:
        canales = (foto / np.maximum(foto.mean(axis=0), 1e-3)) ** contraste
        textura = textura * (1 - fuego) + canales * fuego
    cuerpo = objetivo[None, :] * textura
    # Cuánta luz tiene cada faceta por ENCIMA del promedio, de 0 a 1 (al tope
    # el 10 % más claro). Con fuerza 0, nada de blanco.
    tope = float(np.quantile(relativo, 0.9))
    luz = fuerza * np.clip((relativo - 1) / max(tope - 1, 1e-3), 0, 1)[:, None]
    peso = 1 - luz  # cuánto de cada píxel es cuerpo y no reflejo

    def promedio(x):
        return (x * peso).sum(axis=0) / max(float(peso.sum()), 1e-3)

    for _ in range(VUELTAS_DE_AJUSTE):
        cuerpo = np.clip(cuerpo * (objetivo / np.maximum(promedio(cuerpo), 1e-3)), 0, 1)
        # Si un canal ya topó en las facetas claras (un color muy vivo o el
        # blanco), la multiplicación no alcanza: se sube parejo lo que falta.
        cuerpo = np.clip(cuerpo + (objetivo - promedio(cuerpo)), 0, 1)
    return cuerpo * peso + luz


def _recortar(imagen, margen: int = 24):
    """Quita el blanco de sobra alrededor. Una foto con marco parece un error."""
    import numpy as np

    a = np.asarray(imagen.convert("L"))
    filas = np.where(a.min(axis=1) < 245)[0]
    columnas = np.where(a.min(axis=0) < 245)[0]
    if not len(filas) or not len(columnas):
        return imagen
    return imagen.crop(
        (
            max(int(columnas[0]) - margen, 0),
            max(int(filas[0]) - margen, 0),
            min(int(columnas[-1]) + margen, imagen.width),
            min(int(filas[-1]) + margen, imagen.height),
        )
    )
