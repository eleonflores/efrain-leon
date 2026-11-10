"""Extracción del parte por reglas para el dictado típico; devuelve el mismo `Dictado` que el LLM."""

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
    ("presion_descarga_local", re.compile(rf"{NUM}(?: (?P<u>{_UNIDAD_RE}))? de descarga"), None),
    ("presion_diferencial", re.compile(rf"{NUM}(?: de)? (?:de )?diferencial"), None),
    ("nivel", re.compile(rf"(?:esta en|marca) {NUM} metros?"), None),
    ("temperatura_rodamiento_ir", re.compile(rf"(?<!motor )(?:rodamiento,? )?(?:me dio|medio|marca|esta en) {NUM} grados"), None),
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
# "la bomba" / "el filtro" sin decir cuál, con o sin artículo
GENERICOS = re.compile(r"\b(?:la )?(bomba)\b(?! (?:uno|dos|tres)\b)|\b(?:el )?(filtro)\b(?! (?:a|b)\b)")
_NOMBRE_GENERICO = {"bomba": "la bomba", "filtro": "el filtro"}
SIN_NOVEDAD = re.compile(r"sin novedad|todo normal|todo en orden")
CONECTORES = re.compile(r"\b(ah,? y|tambien|despues|ademas)\b")


# "a uno estar en…", "las dos está en…" → "la uno …", "la dos …"
_NOMBRE_MAL_TRANSCRIPTO = re.compile(r"(^|[.,;] ?)(?:a|ah|las|el) (uno|dos|tres)\b")
GENERICO_POR_VARIABLE = {"presion_descarga_local": "la bomba", "temperatura_rodamiento_ir": "la bomba",
                         "temperatura_motor_ir": "la bomba", "presion_diferencial": "el filtro", "nivel": "el pulmon"}


def _norm(texto: str) -> str:
    t = re.sub(r"\s+", " ", sin_tildes(texto.lower())).strip()
    return _NOMBRE_MAL_TRANSCRIPTO.sub(r"\1la \2", t)


def _equipo_en(clausula: str, planta: Planta, ultimo: bool = False) -> str | None:
    """El nombre de equipo que aparece en la cláusula (como lo dijo): el primero, o el último si `ultimo`."""
    menciones: list[tuple[int, int, str]] = []          # (inicio, -largo, nombre)
    for e in planta.equipos.values():
        for n in e.nombres:
            for m in re.finditer(rf"\b{re.escape(_norm(n))}\b", clausula):
                menciones.append((m.start(), -len(n), n))
    for g in GENERICOS.finditer(clausula):               # un nombre específico en la misma posición gana
        menciones.append((g.start(), 0, _NOMBRE_GENERICO[g.group(1) or g.group(2)]))
    if not menciones:
        return None
    menciones.sort()
    if not ultimo:
        return menciones[0][2]
    inicio = max(m[0] for m in menciones)
    return min((m for m in menciones if m[0] == inicio), key=lambda m: m[1])[2]


def _unidad_contradice(equipo: str, variable: str, unidad: str | None, planta: Planta) -> bool:
    if variable != "presion_descarga_local" or unidad is None:
        return False
    tag = planta.resolver(equipo)
    return tag is not None and planta.equipos[tag].unidad_manometro not in (None, unidad)


def extraer(texto: str, planta: Planta) -> Dictado | None:
    """`texto` ya pasó por `normalizar_numeros`. None si las reglas no alcanzan para explicar la nota."""
    dictado, completo = extraer_con_cobertura(texto, planta)
    return dictado if completo else None


def extraer_con_cobertura(texto: str, planta: Planta) -> tuple[Dictado | None, bool]:
    """(lo que las reglas pudieron leer, si explicaron todos los números de la nota)."""
    t = CONECTORES.sub(" ", _norm(texto))
    # Corta en fin de oración (no en el punto decimal) y en comas, salvo "parada, en reserva" o "disparada, no arranca".
    clausulas = [c.strip(" ,") for c in re.split(r"\.(?!\d)|;|,(?! ?(?:no|que|en reserva)\b)", t) if c.strip(" ,")]
    filas: list[FilaDictada] = []
    equipo: str | None = None
    numeros_usados = 0
    for c in clausulas:
        equipo_previo = equipo
        equipo = _equipo_en(c, planta, ultimo=True) or equipo
        if REBALSE.search(c):
            fila_nivel = next((f for f in reversed(filas) if f.variable == "nivel"), None)
            if fila_nivel:
                fila_nivel.observacion = "rebalse a pileta"
        lecturas: list[tuple[int, FilaDictada]] = []
        for variable, patron, _ in LECTURAS:
            for m in patron.finditer(c):
                en_la_clausula = _equipo_en(c[:m.start()], planta, ultimo=True)
                equipo_fila = en_la_clausula or equipo_previo or GENERICO_POR_VARIABLE.get(variable)
                if equipo_fila is None:
                    continue
                unidad = UNIDAD.get(m.groupdict().get("u") or "")
                if not en_la_clausula and _unidad_contradice(equipo_fila, variable, unidad, planta):
                    equipo_fila = "la bomba"
                if variable == "nivel":
                    unidad = "m"
                elif variable.startswith("temperatura"):
                    unidad = "degC"
                lecturas.append((m.start(), FilaDictada(equipo=equipo_fila, variable=variable, valor=float(m.group(1)),
                                                        unidad=unidad, observacion=None, con_foto=False)))
        for _, fila in sorted(lecturas, key=lambda x: x[0]):      # en el orden en que las dictó
            filas.append(fila)
            numeros_usados += 1
        for variable, patron, obs in OBSERVACIONES:
            m = patron.search(c)
            if not m or equipo is None:
                continue
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
    return Dictado(filas=filas), len(numeros) == numeros_usados
