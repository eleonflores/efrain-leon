import re

import pytest

from sistema.rag.consulta import (
    FALLA_PLANTA, FALLAS_FABRICANTE, codigos_en, equipos_en, expandir_fallas, preparar,
)
from sistema.rag.corpus import cargar_corpus


def test_codigos_de_falla_repuesto_orden_y_tarea():
    texto = "TX-T07 en la OT-25-0026, repuesto 350-EMP-03 (nuevo TX-EMP-KIT), tarea T-B-EMP, falla f03 y FC-T02"
    assert codigos_en(texto) == ["TX-T07", "OT-25-0026", "350-EMP-03", "TX-EMP-KIT", "T-B-EMP", "F03", "FC-T02"]


def test_no_toma_fechas_ni_palabras_comunes_como_codigos():
    assert codigos_en("OT-24-0001 · 2024-10-03 · B-101 · se cambió el kit, físico-químico") == ["OT-24-0001", "B-101"]
    assert codigos_en("¿a qué hora son las recorridas?") == []


def test_la_tabla_de_fallas_es_la_del_mbp4():
    tabla = cargar_corpus().por_cita()["MBP-4 §6.1"].texto
    desde_corpus = {}
    for f, fabricante in re.findall(r"^(F\d{2}) \| [^|]+ \| ([^|]+) \|", tabla, re.M):
        desde_corpus[f] = tuple(c.strip() for c in fabricante.split("/"))
    assert desde_corpus == FALLAS_FABRICANTE
    assert FALLA_PLANTA["TX-T07"] == "F09" and FALLA_PLANTA["FC-T04"] == "F10"


@pytest.mark.parametrize("entrada, esperado", [
    (["TX-T07"], ["TX-T07", "F09"]),
    (["F09"], ["F09", "TX-T07"]),
    (["F10"], ["F10", "TX-T08", "FC-T04"]),
    (["FC-T02", "OT-25-0026"], ["FC-T02", "OT-25-0026", "F08"]),
    (["TX-T11"], ["TX-T11"]),  # sin correspondencia en el catálogo de la planta
])
def test_expansion_de_fallas(entrada, esperado):
    assert expandir_fallas(entrada) == esperado


@pytest.mark.parametrize("texto, tags", [
    ("B3 pierde por la empaquetadura", ["B-103"]),
    ("la del fondo y la uno", ["B-103", "B-101"]),
    ("el caudalímetro marcaba más", ["FT-401"]),
    ("cuántas bombas cavitan", []),
])
def test_equipos_por_nombre_de_campo(texto, tags):
    assert equipos_en(texto) == tags


def test_preparar_expande_codigos_y_equipos():
    c = preparar("¿qué hago con una  TX-T07 en la dos?")
    assert c.codigos == ("TX-T07", "F09") and c.equipos == ("B-102",)
    assert c.pregunta == "¿qué hago con una TX-T07 en la dos?"
    assert "F09" in c.texto_lexico and "B-102 B2 bomba 2" in c.texto_lexico


def test_preparar_sin_expansion():
    c = preparar("¿qué hago con una TX-T07 en la dos?", expandir_codigos=False, expandir_equipos=False)
    assert c.codigos == ("TX-T07",) and c.texto_lexico == c.pregunta


def test_los_nombres_de_equipos_y_modelos_no_van_a_la_lista_de_codigos():
    c = preparar("aceite de la TX-350 de PIA-3 en la B-101 y B3")
    assert c.codigos == () and c.equipos == ("B-101", "B-103")
