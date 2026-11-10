"""Preparación de la consulta: códigos, equipos y expansión con el catálogo de fallas del MBP-4 §6.

Los embeddings representan mal los identificadores exactos (`TX-T07`, `OT-25-0026`, `350-EMP-03`) y el stemming
`spanish` de Postgres los parte en pedazos (`OT-25-0026` → `ot`, `-25`, `-0026`; `B-101` → `b`, `-101`). Por eso los
códigos se extraen aparte, con la misma función para los fragmentos (al indexar) y para la pregunta, y alimentan una
tercera lista de la búsqueda híbrida que solo mira coincidencias exactas de código.

Dos expansiones, las dos medidas en `evaluacion/rag/`:

- **Fallas**: los fabricantes usan sus códigos (`TX-T07`, `FC-T02`) y la planta usa F01–F10. La correspondencia es la
  tabla del MBP-4 §6.1; si la pregunta trae uno, se agrega el otro, así "¿qué es la TX-T07?" encuentra también la
  ficha F09 de la operadora y una pregunta por F09 encuentra la sección del fabricante.
- **Equipos**: en campo se dice "la dos", "B2", "la del fondo" (MBP-4 §2.2 y §4.4). Se agrega el TAG y las
  abreviaturas que se usan en las órdenes, para que el texto libre del historial ("B2 cavita") coincida.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# MBP-4 §6.1 (resumen del catálogo): código de la planta → códigos del fabricante (TX = Trimax, FC = Filtrapat).
FALLAS_FABRICANTE: dict[str, tuple[str, ...]] = {
    "F01": ("TX-T01",), "F02": ("TX-T02",), "F03": ("TX-T03",), "F04": ("TX-T04",), "F05": ("TX-T05",),
    "F06": ("TX-T06",), "F07": ("FC-T01",), "F08": ("FC-T02",), "F09": ("TX-T07",), "F10": ("TX-T08", "FC-T04"),
}
FALLA_PLANTA: dict[str, str] = {fab: f for f, fabs in FALLAS_FABRICANTE.items() for fab in fabs}

# MBP-4 §2.2 (nombres de campo) y §4.4 (abreviaturas de la planilla): TAG → cómo aparece en el texto libre.
ALIAS_EQUIPOS: dict[str, tuple[str, ...]] = {
    "B-101": ("la uno", "la 1", "la de la punta", "la del portón", "bomba uno", "bomba 1", "b1", "bba 1", "b-101",
              "b101"),
    "B-102": ("la dos", "la 2", "la del medio", "bomba dos", "bomba 2", "b2", "bba 2", "b-102", "b102"),
    "B-103": ("la tres", "la 3", "la del fondo", "la de reserva", "bomba tres", "bomba 3", "b3", "bba 3", "b-103",
              "b103"),
    "F-201A": ("filtro a", "el primario", "el de la izquierda", "el grueso", "fa", "filt a", "f-201a", "f201a"),
    "F-201B": ("filtro b", "el secundario", "el de la derecha", "el fino", "fb", "filt b", "f-201b", "f201b"),
    "TK-301": ("el pulmón", "el tanque", "tanque pulmón", "tk-301"),
    "FT-401": ("el caudalímetro", "caudalímetro", "el colector", "ft-401"),
}
# Lo que se agrega a la consulta léxica cuando se nombra un equipo: TAG y abreviaturas de las órdenes.
EXPANSION_EQUIPOS: dict[str, str] = {
    "B-101": "B-101 B1 bomba 1", "B-102": "B-102 B2 bomba 2", "B-103": "B-103 B3 bomba 3",
    "F-201A": "F-201A FA primario", "F-201B": "F-201B FB secundario", "TK-301": "TK-301 tanque",
    "FT-401": "FT-401 caudalímetro",
}

# Nombres que tienen forma de código pero no identifican una falla, un repuesto ni una orden: aparecen en decenas de
# fragmentos y en la lista de códigos solo meterían ruido. Los equipos van por la expansión léxica.
NOMBRES_NO_CODIGO = frozenset({
    "B-101", "B-102", "B-103", "F-201A", "F-201B", "TK-301", "FT-401", "B1", "B2", "B3",
    "PIA-1", "PIA-2", "PIA-3", "TX-250", "TX-350", "TX-500", "FC-24", "FC-48", "FC-96",
})

# Un código es una palabra con guion, letras y algún dígito (TX-T07, OT-25-0026, B-101, 350-EMP-03; no una fecha), una
# palabra en mayúsculas con guion (T-B-EMP, TX-VAL-KIT) o un código corto de letra y número (F03, S1, P2).
_CON_GUION_Y_DIGITO = re.compile(r"(?<![\w-])(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+(?![\w-])")
_MAYUSCULAS_CON_GUION = re.compile(r"(?<![\w-])[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+(?![\w-])")
_CORTO = re.compile(r"(?<![\w-])(?:[Ff]\d{2}|[A-Z]{1,2}\d{1,2})(?![\w-])")


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def codigos_en(texto: str) -> list[str]:
    """Códigos del texto, en mayúsculas y sin repetir, en orden de aparición."""
    hallados: list[tuple[int, str]] = []
    for patron in (_CON_GUION_Y_DIGITO, _MAYUSCULAS_CON_GUION, _CORTO):
        hallados += [(m.start(), m.group(0).upper()) for m in patron.finditer(texto)]
    return list(dict.fromkeys(c for _, c in sorted(hallados)))


def expandir_fallas(codigos: list[str]) -> list[str]:
    """Agrega la correspondencia del MBP-4 §6.1: TX-T07 → F09, F10 → TX-T08 y FC-T04."""
    salida = list(codigos)
    for c in codigos:
        salida += [FALLA_PLANTA[c]] if c in FALLA_PLANTA else list(FALLAS_FABRICANTE.get(c, ()))
    return list(dict.fromkeys(salida))


def equipos_en(texto: str) -> list[str]:
    """TAG de los equipos nombrados en el texto (por TAG, abreviatura o nombre de campo), sin repetir."""
    t = " " + re.sub(r"[^a-z0-9-]+", " ", _sin_tildes(texto.lower())) + " "
    hallados = []
    for tag, alias in ALIAS_EQUIPOS.items():
        posiciones = [t.find(f" {_sin_tildes(a)} ") for a in alias]
        posiciones = [p for p in posiciones if p >= 0]
        if posiciones:
            hallados.append((min(posiciones), tag))
    return [tag for _, tag in sorted(hallados)]


@dataclass(frozen=True)
class Consulta:
    """La pregunta lista para las tres búsquedas: semántica (texto tal cual), léxica (con expansión) y por código."""

    pregunta: str
    texto_lexico: str
    codigos: tuple[str, ...]
    equipos: tuple[str, ...]


def preparar(pregunta: str, *, expandir_codigos: bool = True, expandir_equipos: bool = True) -> Consulta:
    pregunta = " ".join(pregunta.split())
    codigos = [c for c in codigos_en(pregunta) if c not in NOMBRES_NO_CODIGO]
    if expandir_codigos:
        codigos = expandir_fallas(codigos)
    equipos = equipos_en(pregunta)
    extra = [c for c in codigos if c not in pregunta.upper()]
    if expandir_equipos:
        extra += [EXPANSION_EQUIPOS[e] for e in equipos]
    texto_lexico = " ".join([pregunta, *extra])
    return Consulta(pregunta, texto_lexico, tuple(codigos), tuple(equipos))
