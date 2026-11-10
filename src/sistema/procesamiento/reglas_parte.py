"""Extracción del parte por reglas: el camino rápido para el dictado típico del operador.

El operador dicta con frases regulares ("la dos está en 1640 psi de descarga", "el filtro B me dio 1.8 de
diferencial", "en la uno, el rodamiento me dio 52 grados con la pistola"). Medido en la PC de trabajo, el LLM local
tarda 40 a 80 s por nota en 2 CPU (`evaluacion/llm/`), y en la corrección la planta no espera tanto: estas reglas
resuelven el caso típico en milisegundos y devuelven el mismo `Dictado` que el LLM, validado con el mismo esquema.

Si las reglas no explican todos los números de la nota (habla libre, una nota en vivo, una frase que no conocen),
`extraer` devuelve None y la nota va al LLM.
"""

from __future__ import annotations

import re

from sistema.dominio.planta import Planta
from sistema.procesamiento.numeros import sin_tildes
from sistema.procesamiento.parte import Dictado, FilaDictada

NUM = r"(\d+(?:\.\d+)?)"
UNIDAD = {"psi": "psi", "libras": "psi", "libra": "psi", "kilos": "kg/cm2", "kilo": "kg/cm2",
          "kilogramos": "kg/cm2", "bar": "bar", "bares": "bar"}
_UNIDAD_RE = "|".join(sorted(UNIDAD, key=len, reverse=True))

# (variable, patrón, observación fija). El primer grupo numérico es el valor.
LECTURAS = [
    # Sin exigir el "está en": la transcripción a veces lo pierde ("la bomba Steinwil 600 psi de descarga").
    ("presion_descarga_local", re.compile(rf"{NUM}(?: (?P<u>{_UNIDAD_RE}))? de descarga"), None),
    ("presion_diferencial", re.compile(rf"{NUM}(?: de)? (?:de )?diferencial"), None),
    ("nivel", re.compile(rf"(?:esta en|marca) {NUM} metros?"), None),
    ("temperatura_rodamiento_ir", re.compile(rf"rodamiento (?:me dio|medio|marca|esta en) {NUM} grados"), None),
    ("temperatura_motor_ir", re.compile(rf"motor (?:me dio|medio|marca|esta en) {NUM} grados"), None),
]
OBSERVACIONES = [
    ("goteo_empaquetadura", re.compile(r"(?:pierde bastante|chorrea)[^.]*empaquetadura"), "pérdida importante por empaquetadura"),
    ("goteo_empaquetadura", re.compile(r"(?:gotea|goteando|pierde|perdida)[^.]*empaquetadura"), "goteo por empaquetadura"),
    ("nivel_aceite_visor", re.compile(r"casi no tiene aceite"), "nivel de aceite muy bajo"),
    ("nivel_aceite_visor", re.compile(r"(?:visor de aceite|aceite)[^.]*\bbajo"), "nivel de aceite bajo"),
    ("estado_correas", re.compile(r"correas (?:estan |esta )?(?P<x>[a-z]+(?: y [a-z]+)?)"), "correas {x}"),
    ("ruido", re.compile(r"golpeteo metalico"), "hace un golpeteo metálico"),
    ("ruido", re.compile(r"piedras adentro"), "suena como si tuviera piedras adentro"),
    ("ruido", re.compile(r"ruido raro de rodamiento"), "tiene un ruido raro de rodamiento"),
    ("estado", re.compile(r"parada,? en reserva"), "parada, en reserva"),
    ("estado", re.compile(r"parada por mantenimiento"), "parada por mantenimiento"),
    ("estado", re.compile(r"disparada|no arranca"), "disparada, no arranca"),
]
REBALSE = re.compile(r"rebalsando|rebalsa")
FOTO = re.compile(r"(?:le )?saque (?:una )?fotos?")
GENERICOS = re.compile(r"\b(la bomba|el filtro)\b")
SIN_NOVEDAD = re.compile(r"sin novedad|todo normal|todo en orden")
CONECTORES = re.compile(r"\b(ah,? y|tambien|despues|ademas)\b")


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", sin_tildes(texto.lower())).strip()


def _equipo_en(clausula: str, planta: Planta) -> str | None:
    """El nombre de equipo que aparece en la cláusula (como lo dijo), o None."""
    mejor: tuple[int, str] | None = None
    for e in planta.equipos.values():
        for n in e.nombres:
            m = re.search(rf"\b{re.escape(_norm(n))}\b", clausula)
            if m and (mejor is None or m.start() < mejor[0] or (m.start() == mejor[0] and len(n) > len(mejor[1]))):
                mejor = (m.start(), n)
    g = GENERICOS.search(clausula)
    if g and (mejor is None or g.start() < mejor[0]):
        return g.group(1)
    return mejor[1] if mejor else None


def extraer(texto: str, planta: Planta) -> Dictado | None:
    """`texto` ya pasó por `normalizar_numeros`. None si las reglas no alcanzan para explicar la nota."""
    dictado, completo = extraer_con_cobertura(texto, planta)
    return dictado if completo else None


def extraer_con_cobertura(texto: str, planta: Planta) -> tuple[Dictado | None, bool]:
    """Lo que las reglas pudieron leer y si explicaron todos los números de la nota. Lo parcial sirve de respaldo si
    el LLM no llega a tiempo: mejor un borrador incompleto que el operador corrige que ninguno."""
    t = CONECTORES.sub(" ", _norm(texto))
    # Corta en fin de oración (no en el punto decimal) y en comas, salvo "parada, en reserva" o "disparada, no arranca".
    clausulas = [c.strip(" ,") for c in re.split(r"\.(?!\d)|;|,(?! ?(?:no|que|en reserva)\b)", t) if c.strip(" ,")]
    filas: list[FilaDictada] = []
    equipo: str | None = None
    numeros_usados = 0
    for c in clausulas:
        equipo = _equipo_en(c, planta) or equipo
        if REBALSE.search(c):
            fila_nivel = next((f for f in reversed(filas) if f.variable == "nivel"), None)
            if fila_nivel:
                fila_nivel.observacion = "rebalse a pileta"
        for variable, patron, _ in LECTURAS:
            for m in patron.finditer(c):
                if equipo is None:
                    return (Dictado(filas=filas) if filas else None), False
                valor = float(m.group(1))
                unidad = UNIDAD.get(m.groupdict().get("u") or "")
                if variable == "nivel":
                    unidad = "m"
                elif variable.startswith("temperatura"):
                    unidad = "degC"
                filas.append(FilaDictada(equipo=equipo, variable=variable, valor=valor, unidad=unidad,
                                         observacion=None, con_foto=False))
                numeros_usados += 1
        for variable, patron, obs in OBSERVACIONES:
            m = patron.search(c)
            if not m:
                continue
            if equipo is None:
                return (Dictado(filas=filas) if filas else None), False
            if any(f.variable == variable and f.equipo == equipo for f in filas):
                continue
            filas.append(FilaDictada(equipo=equipo, variable=variable, valor=None, unidad=None,
                                     observacion=obs.format(**m.groupdict()) if "{" in obs else obs, con_foto=False))
        if FOTO.search(c) and filas:                 # "le saqué foto": de lo último que dijo
            filas[-1].con_foto = True
    numeros = re.findall(r"\b\d+(?:\.\d+)?\b", t)
    if not filas and not numeros and SIN_NOVEDAD.search(t):
        return Dictado(filas=[]), True
    if not filas:
        return None, False
    # Si hay números que las reglas no explican, que decida el LLM (con lo de las reglas como respaldo).
    return Dictado(filas=filas), len(numeros) == numeros_usados
