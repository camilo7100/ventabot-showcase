"""El cuestionario para Lía: lo que el ERP todavía SUPONE, preguntado claro.

Camilo (02/10): «dame un PDF y un Excel para pasarlo a Luna Joyas y que
llene todo y no omita nada; donde no sabe, que coloque no sé». El costo de una
pieza (hoja Costeo) mezcla datos (gramos, precio de la plata, precios) con
supuestos (qué incluye el taller, lo de la familia, las piedras…). Cada
respuesta de Lía reemplaza un supuesto; un «no sé» lo deja como está.

Todo aquí es puro: las preguntas, cómo se lee una respuesta escrita a mano
(«$1.200.000», «600 mil», «8 %», «no sé») y qué supuesto de Costeo cambia.
Escribir el Excel y pasarlo al ERP es de `app.adapters.erp.cuestionario`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: Lo que se escribe cuando no se sabe. Cualquier variante vale («nose», «NS»).
NO_SE = "NO SÉ"
#: El mínimo que gana Lía (la dueña): salario mínimo 2026 + auxilio de
#: transporte (decretos 1469 y 1470 de 2025). Camilo: «si gana menos, no come».
SALARIO_MINIMO_2026 = 2_000_000


@dataclass(frozen=True)
class Pregunta:
    id: str
    tema: str
    texto: str
    #: Por qué se pregunta, en una línea (va al lado, en el Excel y el PDF).
    para_que: str
    #: Cómo se contesta: «$ al mes», «sí / no», «texto»…
    unidad: str
    #: El supuesto de la hoja Costeo que cambia (clave de `costeo.SUPUESTOS`),
    #: o el material de Cat_Materiales (`material:<nombre>`), o None.
    destino: str | None = None
    #: Cómo se convierte la respuesta: «pesos», «porcentaje», «texto».
    tipo: str = "pesos"


PREGUNTAS: tuple[Pregunta, ...] = (
    # -- El taller ----------------------------------------------------------
    Pregunta(
        "T1",
        "El taller",
        "¿Cuánto pagas de ARRIENDO del taller al mes? (0 si es propio)",
        "Hoy el ERP no cuenta arriendo ni servicios (los ~$23 M eran el equipo)",
        "$ al mes",
        "taller_arriendo",
    ),
    Pregunta(
        "T2",
        "El taller",
        "¿Cuánto pagas de SERVICIOS del taller al mes? (luz, agua, gas, internet)",
        "Parte del taller",
        "$ al mes",
        "taller_servicios",
    ),
    Pregunta(
        "T3",
        "El taller",
        "¿Cuánto gastas al AÑO en mantenimiento, reparaciones y herramientas pequeñas?",
        "Parte del taller",
        "$ al año",
        "taller_mantenimiento",
    ),
    Pregunta(
        "T4",
        "El taller",
        "¿Hay otros gastos del taller que no estén arriba? ¿Cuánto suman al AÑO?",
        "Parte del taller",
        "$ al año",
        "taller_otros",
    ),
    # -- Las personas -------------------------------------------------------
    Pregunta(
        "P1",
        "Las personas",
        "¿Cuánto debería ganar Lía al mes? (como mínimo $2.000.000: el mínimo "
        "2026 con auxilio de transporte)",
        "El negocio es de Lía: su trabajo es un costo aunque no se lo pague",
        "$ al mes",
        "salario",
    ),
    Pregunta(
        "P2",
        "Las personas",
        "¿Cuánto se le paga a la MAMÁ al mes? ¿Qué hace y cuántas horas?",
        "Hoy el ERP supone $600.000 al mes",
        "$ al mes",
        "mama",
    ),
    Pregunta(
        "P3",
        "Las personas",
        "¿Cuánto se le paga al TÍO al mes? ¿Qué hace?",
        "Hoy el ERP supone $400.000 al mes",
        "$ al mes",
        "tio",
    ),
    Pregunta(
        "P4",
        "Las personas",
        "Al ayudante, ¿se le siguen pagando $14.000 por anillo? ¿Se le paga algo más "
        "(transporte, bonos, piezas que repite)?",
        "Es la mano de obra de cada pieza en la receta",
        "$ por anillo",
        "mano_de_obra",
    ),
    Pregunta(
        "P5",
        "Las personas",
        "¿Hay alguien más que ayude y reciba plata? ¿Quién y cuánto al mes?",
        "Para no dejar a nadie por fuera",
        "texto",
        tipo="texto",
    ),
    # -- La plata y las piedras --------------------------------------------
    Pregunta(
        "M1",
        "Plata y piedras",
        "De cada 100 gramos de plata que se funden, ¿cuántos se PIERDEN (no se "
        "recuperan)?",
        "Hoy el ERP supone 8 %",
        "gramos de cada 100",
        "merma",
        "porcentaje",
    ),
    Pregunta(
        "M2",
        "Plata y piedras",
        "¿Cuánto cuesta UNA piedra de corazón (la grande)?",
        "Hoy el ERP supone $1.500",
        "$ cada una",
        "material:Circón corazón",
    ),
    Pregunta(
        "M3",
        "Plata y piedras",
        "¿Cuánto cuesta UNA piedrita de los deditos? (cada huellita lleva 4)",
        "Hoy el ERP supone $300 (antes ni se contaban)",
        "$ cada una",
        "material:Circón dedito",
    ),
    Pregunta(
        "M4",
        "Plata y piedras",
        "¿Cuánto cuesta la CADENA de plata (45 cm)?",
        "Camilo dijo $30.000",
        "$ cada una",
        "material:Cadena plata 925 (45 cm)",
    ),
    Pregunta(
        "M5",
        "Plata y piedras",
        "¿A quién le compras la plata y cada cuánto? ¿Cuántos gramos compras cada vez?",
        "Para que las compras del mes cuadren con el inventario",
        "texto",
        tipo="texto",
    ),
    Pregunta(
        "M6",
        "Plata y piedras",
        "¿Cuántos gramos de plata, piedras de corazón y piedritas tienes HOY guardados?",
        "Es el inventario con el que arranca el ERP",
        "texto (ej.: 120 g · 40 corazones · 200 piedritas)",
        tipo="texto",
    ),
    # -- Insumos y empaque --------------------------------------------------
    Pregunta(
        "I1",
        "Insumos y empaque",
        "¿Cuánto cuesta el ESTUCHE de cada anillo?",
        "Hoy el ERP supone $8.000",
        "$ cada uno",
        "material:Estuche básico",
    ),
    Pregunta(
        "I2",
        "Insumos y empaque",
        "¿Cuánto cuesta la CAJA de envío?",
        "Hoy el ERP supone $3.500",
        "$ cada una",
        "material:Caja de envío",
    ),
    Pregunta(
        "I3",
        "Insumos y empaque",
        "¿Cuánto cuesta la TARJETA que va con el anillo?",
        "Hoy el ERP supone $800",
        "$ cada una",
        "material:Tarjeta regalo",
    ),
    Pregunta(
        "I4",
        "Insumos y empaque",
        "¿Cuánto cuesta el PAPEL SEDA de cada pedido?",
        "Hoy el ERP supone $200",
        "$ por pedido",
        "material:Papel seda",
    ),
    Pregunta(
        "I5",
        "Insumos y empaque",
        "Cera, yeso, lijas, pulidor, gasolina y silicona: ¿cuánto gastas en TODO "
        "eso al mes, más o menos?",
        "Hoy el ERP supone ~$2.640 por pieza (sale de una guía vieja)",
        "$ al mes",
        tipo="pesos",
    ),
    # -- Lo que se paga sin pensar -----------------------------------------
    Pregunta(
        "G1",
        "Lo que se paga sin pensar",
        "Taxis, domicilios y diligencias (comprar materiales, llevar piezas): "
        "¿cuánto al mes?",
        "Hoy el ERP supone $200.000 al mes",
        "$ al mes",
        "diligencias",
    ),
    Pregunta(
        "G2",
        "Lo que se paga sin pensar",
        "¿Cuánto pagas al mes en comisiones del banco, Nequi o Daviplata?",
        "No está en el ERP",
        "$ al mes",
        tipo="pesos",
    ),
    Pregunta(
        "G3",
        "Lo que se paga sin pensar",
        "¿Pagas contador, impuestos (DIAN, ICA) o Cámara de Comercio? ¿Cuánto al AÑO?",
        "No está en el ERP",
        "$ al año",
        tipo="pesos",
    ),
    Pregunta(
        "G4",
        "Lo que se paga sin pensar",
        "Página web, dominio, apps y plan de celular del negocio: ¿cuánto al mes?",
        "No está en el ERP",
        "$ al mes",
        tipo="pesos",
    ),
    Pregunta(
        "G5",
        "Lo que se paga sin pensar",
        "¿Cuántas piezas al mes toca REPETIR o reponer (talla, daño, garantía, "
        "envío perdido)?",
        "El colchón del 10 % está para eso; si son muy pocas, se puede bajar",
        "piezas al mes",
        tipo="texto",
    ),
    # -- Equipos -------------------------------------------------------------
    Pregunta(
        "E1",
        "Equipos",
        "Camilo pasó la lista del equipo (laminador, horno, vaccum, ultrasonido, "
        "barril de agujas, vulcanizadora, motor, inyectora, 2 Foredom, 3 cajones: "
        "$17,4 M). ¿Falta alguna máquina o herramienta? Anótala en la hoja «Equipos». "
        "¿Cuántos años dura cada una, más o menos?",
        "Hoy el ERP supone 10 años para cada equipo",
        "hoja Equipos y años",
        tipo="texto",
    ),
    # -- Ventas ---------------------------------------------------------------
    Pregunta(
        "V1",
        "Ventas",
        "¿Vendes por fuera de WhatsApp (en persona, ferias, la página web)? "
        "¿Cuánto al mes, más o menos?",
        "El bot solo ve lo de WhatsApp; lo demás va en la hoja «Ventas fuera del bot»",
        "texto",
        tipo="texto",
    ),
    Pregunta(
        "V2",
        "Ventas",
        "¿Cuánto les queda de verdad al mes, después de pagar todo (sin contar el "
        "sueldo de Lía)?",
        "Camilo calcula ~$800.000 y el ERP, con sus supuestos, ~$4.000.000 en "
        "efectivo: así se sabe qué falta (el sueldo de Lía, el arriendo…)",
        "$ al mes",
        tipo="pesos",
    ),
)

#: Las preguntas que juntas son el taller (Costeo: «Gastos del taller por año»).
PARTES_DEL_TALLER = {
    "taller_arriendo": 12,
    "taller_servicios": 12,
    "taller_mantenimiento": 1,
    "taller_otros": 1,
}


def _plano(texto: str) -> str:
    sin = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sin if not unicodedata.combining(c)).lower().strip()


def no_sabe(texto) -> bool:
    plano = re.sub(r"[^a-z]", "", _plano(str(texto or "")))
    return plano in {"nose", "ns", "nosabe", "nolose", "nosabemos", "niidea"}


def leer_pesos(texto) -> float | None:
    """«$1.200.000», «1,2 millones», «600 mil», «600k», 1200000 -> pesos.

    None si está vacío, dice «no sé» o no trae un número."""
    if isinstance(texto, int | float):
        return float(texto)
    plano = _plano(str(texto or ""))
    if not plano or no_sabe(plano):
        return None
    m = re.search(r"(\d[\d.,\s]*)\s*(millones|millon|mill|m\b|mil|k\b)?", plano)
    if not m:
        return None
    crudo, escala = m.group(1).strip().replace(" ", ""), m.group(2) or ""
    if escala in ("millones", "millon", "mill", "m", "mil", "k"):
        # «1,2 millones» / «1.5 mil»: la coma o el punto son decimales.
        numero = float(crudo.replace(",", "."))
        return numero * (
            1_000_000 if escala.startswith("m") and escala != "mil" else 1_000
        )
    # «1.200.000» / «1,200,000»: separadores de miles.
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", crudo):
        return float(re.sub(r"[.,]", "", crudo))
    return float(crudo.replace(",", "."))


def leer_porcentaje(texto) -> float | None:
    """«8», «8 %», «0,08», «8 gramos» -> 0.08."""
    numero = leer_pesos(texto)
    if numero is None:
        return None
    return numero / 100 if numero >= 1 else numero


@dataclass
class Respuestas:
    """Lo que contestó Lía, ya leído."""

    #: id de la pregunta -> lo que escribió (tal cual).
    escritas: dict[str, str] = field(default_factory=dict)

    def numero(self, p: Pregunta) -> float | None:
        texto = self.escritas.get(p.id, "")
        return leer_porcentaje(texto) if p.tipo == "porcentaje" else leer_pesos(texto)

    def sin_contestar(self) -> list[Pregunta]:
        """Las que dejó en blanco (un «no sé» SÍ cuenta como contestada)."""
        return [p for p in PREGUNTAS if not str(self.escritas.get(p.id, "")).strip()]


@dataclass(frozen=True)
class CambioDeSupuesto:
    destino: str  # clave de Costeo o «material:<nombre>»
    valor: float
    fuente: str


def cambios_del_costeo(r: Respuestas, fecha: str) -> list[CambioDeSupuesto]:
    """Lo que las respuestas cambian en Costeo y en Cat_Materiales.

    - El taller solo cambia si contestó LAS CUATRO partes (0 vale): a medias
      se quedaría corto y parecería más barato de lo que es.
    - El salario de Lía nunca baja del mínimo (Camilo: «si gana menos, no come»).
    - Un «no sé» o una casilla vacía no cambia nada.
    """
    cambios: list[CambioDeSupuesto] = []
    partes = {p.destino: r.numero(p) for p in PREGUNTAS if p.destino in PARTES_DEL_TALLER}
    if all(v is not None for v in partes.values()):
        total = sum(v * PARTES_DEL_TALLER[k] for k, v in partes.items() if v is not None)
        cambios.append(
            CambioDeSupuesto(
                "taller",
                total,
                f"Lía, cuestionario {fecha}: arriendo y servicios × 12 + "
                "mantenimiento + otros del año",
            )
        )
    for p in PREGUNTAS:
        if not p.destino or p.destino in PARTES_DEL_TALLER:
            continue
        valor = r.numero(p)
        if valor is None:
            continue
        fuente = f"Lía, cuestionario {fecha}: «{r.escritas.get(p.id, '')}»"
        if p.destino == "salario" and valor < SALARIO_MINIMO_2026:
            valor = SALARIO_MINIMO_2026
            fuente += " (sube al mínimo 2026 con auxilio)"
        cambios.append(CambioDeSupuesto(p.destino, valor, fuente))
    return cambios
