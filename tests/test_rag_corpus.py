"""Metadatos del corpus del RAG: vigencia, aplicabilidad a PIA-3, equipos y texto de búsqueda de las órdenes."""

import json

import numpy as np
import pytest

from sistema.rag.corpus import (
    armar_fragmentos, cargar_corpus, expandir_abreviaturas, motivo_no_aplica, ruta_documentos, texto_busqueda_orden,
)
from sistema.rag.embeddings import MODELO_POR_DEFECTO, MODELOS, leer_vectores
from sistema.rag.indice import fila, version_indice


@pytest.fixture(scope="module")
def corpus():
    return cargar_corpus()


@pytest.fixture(scope="module")
def suite():
    return json.loads((ruta_documentos() / "evaluacion" / "retrieval.json").read_text(encoding="utf-8"))


def test_corpus_completo_con_citas_unicas(corpus):
    assert len(corpus) == 701
    assert len(corpus.por_cita()) == 701
    assert sum(f.documento == "historial" for f in corpus.fragmentos) == 243


def test_rev_c_no_vigente_y_rev_d_vigente(corpus):
    por_cita = corpus.por_cita()
    assert not por_cita["TX350-C §3.2"].vigente and por_cita["TX350-C §3.2"].revision == "C"
    assert por_cita["TX350-D §3.2"].vigente and por_cita["TX350-D §3.2"].aplica_pia3
    assert all(not f.vigente for f in corpus.fragmentos if f.documento == "TX350-C")


@pytest.mark.parametrize("cita", ["TX350-D §3.3", "TX350-D §2.1", "FC48-3 §2.1", "MBP-4 §5.3", "MBP-4 §17",
                                  "MBP-4 §17.1", "MBP-4 §17.3", "TX350-D §12.4", "FC48-3 §16.2", "TX350-D §4.6",
                                  "TX350-D §11.2", "FC48-3 §11.1"])
def test_secciones_que_no_aplican_a_pia3(corpus, cita):
    f = corpus.por_cita()[cita]
    assert not f.aplica_pia3 and f.motivo_no_aplica


@pytest.mark.parametrize("cita", ["TX350-D §3.1", "MBP-4 §1.1", "MBP-4 §6.1", "FC48-3 §17.4",
                                  "CT-SVP-2025 §2.5", "historial OT-25-0026"])
def test_secciones_que_aplican(corpus, cita):
    assert corpus.por_cita()[cita].aplica_pia3


def test_el_capitulo_contagia_la_no_aplicabilidad():
    assert motivo_no_aplica(None, "otras-plantas") and motivo_no_aplica("pia1", "otras-plantas")
    assert motivo_no_aplica("limites", "especificaciones") is None


def test_el_filtro_por_defecto_no_saca_ninguna_respuesta_de_la_suite(corpus, suite):
    """Pre-filtrar es seguro: ninguna sección relevante de las 71 preguntas es no vigente o no aplicable."""
    por_cita = corpus.por_cita()
    relevantes = {r for q in suite for r in q["relevantes"]}
    assert all(por_cita[r].vigente and por_cita[r].aplica_pia3 for r in relevantes)
    distractores = {d for q in suite for d in q["distractores"]}
    sobreviven = {d for d in distractores if por_cita[d].vigente and por_cita[d].aplica_pia3}
    assert sobreviven == {"CT-SVP-2025 §2.5", "CT-SVP-2025 §2.1"}  # precios viejos y nuevos: depende de la fecha


def test_metadatos_de_documento_y_de_orden(corpus):
    por_cita = corpus.por_cita()
    bomba = por_cita["TX350-D §8.9"]
    assert bomba.fabricante == "Trimax Industrial S.A." and bomba.equipos == ("B-101", "B-102", "B-103")
    assert bomba.pagina and bomba.tipo_documento == "manual_fabricante"
    orden = por_cita["historial OT-25-0026"]
    assert orden.equipos == ("B-101",) and str(orden.fecha) == "2025-03-11" and orden.seccion == "OT-25-0026"


def test_texto_de_busqueda_de_una_orden():
    texto = ("OT-25-0113 · 2025-11-18 · B-102 · T-B-ACE · propio\nAviso: B2 aceite bajo otra vez\n"
             "Trabajo: 8 lts otra vez en 3 semanas. cbio c/ reten x perdida")
    t = texto_busqueda_orden(texto)
    assert "Equipo B-102 (bomba 2, la dos)" in t and "reposición de aceite del cárter" in t
    assert "bomba 2 aceite bajo" in t and "8 litros" in t and "cambio con reten por perdida" in t
    assert expandir_abreviaturas("dif FA 0,9") == "diferencial filtro A primario 0,9"
    assert expandir_abreviaturas("texto sin abreviaturas, extra") == "texto sin abreviaturas, extra"


def test_el_texto_original_se_conserva_para_mostrar(corpus):
    orden = corpus.por_cita()["historial OT-25-0113"]
    assert orden.texto.startswith("OT-25-0113 · ") and "lts" in orden.texto
    assert "litros" in orden.texto_busqueda and "Historial de PIA-3" in orden.texto_para_embeber()
    seccion = corpus.por_cita()["TX350-D §3.2"]
    assert seccion.texto_busqueda == seccion.texto
    assert seccion.texto_para_embeber().startswith("Bomba alternativa triplex Trimax TX-350 (TX350-D, revisión D).")


def test_armar_fragmentos_con_un_indice_minimo():
    indice = {"documentos": [{"id": "X-1", "titulo": "Manual X", "revision": "B", "vigente": False,
                              "tipo": "manual_fabricante", "emisor": "Fabricante X", "equipos": ["B-101"]}]}
    lineas = [{"id": "X-1 §2", "doc": "X-1", "numero": "2", "titulo": "Opcionales", "clave": "opcionales",
               "pagina": 3, "vigente": False, "texto": "2. Opcionales"},
              {"id": "X-1 §2.1", "doc": "X-1", "numero": "2.1", "titulo": "Kit", "clave": "kit", "pagina": 3,
               "vigente": False, "texto": "2.1 Kit"}]
    a, b = armar_fragmentos(lineas, indice)
    assert not a.aplica_pia3 and not b.aplica_pia3 and not b.vigente
    assert b.fabricante == "Fabricante X" and b.equipos == ("B-101",) and b.revision == "B"


def test_fila_para_postgres(corpus):
    f = corpus.por_cita()["TX350-D §8.9"]
    r = fila(f, np.array([0.5, -0.25], dtype=np.float32))
    assert r[0] == "TX350-D §8.9" and r[-1] == "[0.5,-0.25]"
    assert "TX-T07" in r[14] and r[15] == ["TX-T07"]  # códigos del texto y del título
    assert fila(f, None)[-1] is None
    assert version_indice(MODELOS["e5-small-int8"], "abc", True) != version_indice(MODELOS["e5-small-int8"], "abc",
                                                                                   False)


def test_vectores_precalculados_al_dia_con_el_corpus(corpus):
    """Si cambia el corpus o el armado del texto, hay que volver a correr `--precalcular`."""
    modelo = MODELOS[MODELO_POR_DEFECTO]
    vectores = leer_vectores(modelo.archivo_vectores())
    if vectores is None:
        pytest.skip("sin vectores precalculados (se generan al construir la imagen)")
    assert vectores.huella == corpus.huella() and vectores.modelo == modelo.clave
    assert vectores.vectores.shape == (len(corpus), modelo.dim)
    assert np.allclose(np.linalg.norm(vectores.vectores, axis=1), 1, atol=1e-3)
