"""A dónde va el anillo, y a nombre de quién.

════════════════════════════════════════════════════════════════════════════
POR QUÉ ESTO ESTÁ ANTES DEL COBRO Y NO DESPUÉS
════════════════════════════════════════════════════════════════════════════
El bot pedía el abono en cuanto sabía los colores y la talla. Suena eficiente
y no lo es: una clienta a la que le piden plata a los cuatro mensajes, sin
haberle preguntado siquiera a dónde mandarle el anillo, siente que le están
cobrando, no atendiendo. Y desconfía.

Terminar de armar el pedido —nombre, ciudad, dirección— antes de nombrar el
abono hace justo lo contrario: cada dato que da es una inversión suya en la
compra, y para cuando llega el precio ya está dentro. Es el mismo pedido con
los mismos pasos en otro orden, y el orden es la venta.

Además hace falta de verdad: sin dirección no se despacha nada, y
descubrirlo diez días después —con el anillo hecho y la clienta sin
contestar— es como se pierde un anillo ya fabricado.

════════════════════════════════════════════════════════════════════════════
EL TELÉFONO NO SE PREGUNTA
════════════════════════════════════════════════════════════════════════════
Está escribiendo por WhatsApp: su número ya lo tenemos. Preguntárselo es
decirle que no la estamos escuchando, y es una de esas preguntas que hacen
que la gente se pregunte con quién está hablando.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

#: Lo mínimo para que una transportadora recoja el paquete.
#:
#: No está el teléfono a propósito (lo tenemos), ni el correo (no hace falta
#: para una guía nacional). Cada campo de más es una pregunta de más, y cada
#: pregunta de más pierde gente.
NOMBRE_MAXIMO = 60
DIRECCION_MAXIMA = 200

#: La transportadora de siempre. Se puede cambiar pedido por pedido en el panel.
TRANSPORTADORA = "Coordinadora"

#: Una dirección colombiana de verdad lleva un número. «Mi casa» no sirve
#: para una guía; «Calle 45 #12-30 apto 301» sí.
TIENE_NUMERO = re.compile(r"\d")

#: Palabras que casi siempre aparecen en una dirección. Sirven para
#: reconocerla cuando llega sin que la hayamos pedido.
PALABRAS_DE_DIRECCION = (
    "calle",
    "carrera",
    "cra",
    "cll",
    "avenida",
    "av",
    "diagonal",
    "transversal",
    "manzana",
    "barrio",
    "conjunto",
    "apto",
    "apartamento",
    "torre",
    "casa",
    "kilometro",
    "vereda",
    "#",
)


class DatosDeEnvio(BaseModel):
    """A dónde va y a nombre de quién. Puede estar a medias mientras se pregunta."""

    nombre: str = Field(default="", max_length=NOMBRE_MAXIMO)
    ciudad: str = Field(default="", max_length=60)
    direccion: str = Field(default="", max_length=DIRECCION_MAXIMA)
    #: El de WhatsApp. Se rellena solo, no se pregunta.
    telefono: str = Field(default="", max_length=20)
    #: La cédula y el celular que pide la transportadora para la guía. Se
    #: preguntan al final, con las fotos del anillo (Camilo, 20/09).
    cedula: str = Field(default="", max_length=15)
    celular: str = Field(default="", max_length=15)
    #: «Dejar en portería», «llamar antes». Lo que ella agregue.
    notas: str = Field(default="", max_length=160)
    #: Lo recoge en el punto de recogida (Floridablanca): no hace falta dirección.
    recoge: bool = False
    #: Pidió pagar el envío por adelantado: se le cobra JUNTO CON EL SALDO y no
    #: paga nada al recibir. Lo normal es False: se paga al recibir.
    envio_con_saldo: bool = False
    #: El barrio, aparte (también va dentro de la dirección, como lo escribió).
    #: Separado sirve para ordenar y analizar; la guía usa la dirección entera.
    barrio: str = Field(default="", max_length=80)
    #: Con quién se manda y el número de guía. La guía es OBLIGATORIA para
    #: marcarlo despachado (Camilo, 29/09): va en el mensaje a la clienta.
    transportadora: str = Field(default=TRANSPORTADORA, max_length=40)
    guia: str = Field(default="", max_length=40)

    def falta(self) -> list[str]:
        """Qué queda por preguntar. Vacío = se puede despachar.

        Devuelve claves, no frases: la redacción vive en las plantillas, igual
        que en `Personalizacion`.
        """
        pendientes = []
        if not self.nombre.strip():
            pendientes.append("nombre")
        if self.recoge:
            return pendientes
        if not self.ciudad.strip():
            pendientes.append("ciudad")
        if not self.cedula.strip():
            pendientes.append("cedula")
        if not self.celular.strip():
            pendientes.append("celular")
        if not self.direccion.strip():
            pendientes.append("direccion")
        return pendientes

    def falta_para_tomar_el_pedido(self) -> list[str]:
        """Lo único personal que hace falta ANTES de cobrar: su nombre.

        Los datos de la guía —ciudad, cédula, celular, dirección— se piden al
        final, con las fotos del anillo terminado (Camilo, 20/09). Antes se
        pedían todos al principio y era un formulario a alguien que todavía no
        había comprado.
        """
        return [] if self.nombre.strip() else ["nombre"]

    @property
    def completo(self) -> bool:
        return not self.falta()

    def describir(self) -> str:
        """Como se lo confirmamos a ella y como lo lee quien despacha."""
        lineas = []
        if self.nombre:
            lineas.append(f"A nombre de: {self.nombre}")
        if self.recoge:
            from app.domain.faq import PUNTO_DE_RECOGIDA

            lineas.append(f"Lo recoge en: {PUNTO_DE_RECOGIDA}")
        elif self.direccion or self.ciudad:
            destino = ", ".join(p for p in (self.direccion, self.ciudad) if p)
            lineas.append(f"Dirección: {destino}")
        if self.barrio and self.barrio.lower() not in self.direccion.lower():
            lineas.append(f"Barrio: {self.barrio}")
        if self.cedula:
            lineas.append(f"Cédula: {self.cedula}")
        if self.celular or self.telefono:
            lineas.append(f"Celular: {self.celular or self.telefono}")
        if self.notas:
            lineas.append(f"Nota: {self.notas}")
        if self.guia:
            lineas.append(f"Guía: {self.transportadora} {self.guia}")
        return "\n".join(lineas)


def parece_direccion(texto: str) -> bool:
    """¿Esto es una dirección? Con un número y una palabra de calle, sí.

    Se usa para aceptar una dirección que llega antes de pedirla, no para
    rechazar la que llega cuando SÍ la pedimos: ahí manda el contexto, y una
    clienta que contesta a «¿cuál es tu dirección?» está dando su dirección
    aunque escriba algo raro.
    """
    bajo = (texto or "").lower()
    if not TIENE_NUMERO.search(bajo):
        return False
    return any(p in bajo for p in PALABRAS_DE_DIRECCION)


# ══════════════════════════════════════════════════════════════════════════
#  LEER LOS DATOS DE ENVÍO QUE MANDA ELLA (29/09)
# ══════════════════════════════════════════════════════════════════════════
#
# Con el anillo listo se le pide «Ciudad / Nombre completo / Cédula / Celular /
# Dirección». El 28/09 una clienta los mandó perfectos, uno por renglón, y la
# dirección NO quedó: la IA entendió «mandó todos los datos» pero no la copió.
# Es lo que más importa para despachar, así que Python la lee también: es una
# red de seguridad, no reemplaza lo que la IA sí anotó.

_ETIQUETAS = {
    "ciudad": re.compile(r"^\W*(ciudad|municipio)\b\s*:?\s*(.+)$", re.I),
    "destinatario": re.compile(
        r"^\W*(nombre(\s+completo)?|a\s+nombre\s+de|destinatari[oa]|recibe)\b\s*:?\s*(.+)$",
        re.I,
    ),
    "cedula": re.compile(r"^\W*(c[eé]dula|cc|c\.c\.?|documento)\s*:?\s*(.+)$", re.I),
    "celular": re.compile(r"^\W*(celular|cel|tel[eé]fono|whatsapp)\b\s*:?\s*(.+)$", re.I),
    "direccion": re.compile(r"^\W*(direcci[oó]n\b[^:]*)\s*:\s*(.+)$", re.I),
    "barrio": re.compile(r"^\W*(barrio)\b\s*:\s*(.+)$", re.I),
}
_BARRIO_EN_DIRECCION = re.compile(r"\bbarrio\s+([^,\-–/\n]+)", re.I)


def _solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def leer_datos_de_envio(texto: str | None, ciudades=()) -> dict[str, str]:
    """Los datos de la guía que vienen en un mensaje, uno por renglón.

    Sirve con etiquetas («Ciudad: Bogotá») y sin ellas, en el orden en que se
    piden. Devuelve solo lo que reconoce, y NADA si reconoce menos de dos cosas:
    un «Bogotá» suelto en medio de la charla no es un bloque de datos.
    `ciudades` son las conocidas (la tabla de envíos), para no confundir una
    ciudad con un nombre.
    """
    import unicodedata

    def norma(s: str) -> str:
        s = "".join(
            c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
        )
        return " ".join(s.lower().split())

    conocidas = {norma(c) for c in ciudades}
    datos: dict[str, str] = {}
    for bruto in (texto or "").splitlines():
        linea = bruto.strip().strip("-•*·").strip()
        if not linea:
            continue
        etiquetada = False
        for campo, patron in _ETIQUETAS.items():
            m = patron.match(linea)
            valor = (m.group(m.lastindex or 0) or "").strip() if m else ""
            if valor:
                if campo in ("cedula", "celular"):
                    valor = _solo_digitos(valor)
                if valor and campo not in datos:
                    datos[campo] = valor
                etiquetada = True
                break
        if etiquetada:
            continue
        digitos = _solo_digitos(linea)
        solo_numero = bool(digitos) and not re.sub(r"[\d\s.\-+()]", "", linea)
        if solo_numero:
            if len(digitos) == 10 and digitos.startswith("3") and "celular" not in datos:
                datos["celular"] = digitos
            elif 6 <= len(digitos) <= 11 and "cedula" not in datos:
                datos["cedula"] = digitos
            continue
        if parece_direccion(linea) and "direccion" not in datos:
            datos["direccion"] = linea
            continue
        if TIENE_NUMERO.search(linea):
            continue
        palabras = len(linea.split())
        if norma(linea) in conocidas and "ciudad" not in datos:
            datos["ciudad"] = linea
        elif (palabras >= 2 and "destinatario" not in datos and not conocidas) or (
            palabras >= 2 and "destinatario" not in datos and "ciudad" in datos
        ):
            datos["destinatario"] = linea
        elif "ciudad" not in datos and palabras <= 3:
            datos["ciudad"] = linea
    if "direccion" in datos and "barrio" not in datos:
        m = _BARRIO_EN_DIRECCION.search(datos["direccion"])
        if m:
            datos["barrio"] = m.group(1).strip()
    if "direccion" in datos:
        datos["direccion"] = " ".join(datos["direccion"].split())[:DIRECCION_MAXIMA]
    if "destinatario" in datos:
        datos["destinatario"] = " ".join(datos["destinatario"].split())[:NOMBRE_MAXIMO]
    # Hace falta al menos un dato FUERTE (cédula, celular o dirección): dos
    # renglones sueltos («La verde por favor / Pepe») no son datos de envío.
    fuertes = {"cedula", "celular", "direccion"} & datos.keys()
    return datos if fuertes and len(datos) >= 2 else {}
