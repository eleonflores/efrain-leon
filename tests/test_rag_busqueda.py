"""Lógica de la búsqueda híbrida que no necesita Postgres: RRF, filtro previo, recorte y armado del SQL."""

import numpy as np
import pytest

from sistema.rag.busqueda import (
    BuscadorManuales, Candidato, Filtros, condiciones, fusionar_cc, fusionar_rrf, recortar, sql_listas,
)
from sistema.rag.embeddings import Embedder, VectoresCorpus, leer_vectores


def test_rrf_suma_inversas_de_posicion():
    r = fusionar_rrf({"sem": ["a", "b", "c"], "lex": ["b", "d"]}, k=60)
    puntajes = {c: p for c, p, _ in r}
    assert [c for c, _, _ in r] == ["b", "a", "d", "c"]
    assert puntajes["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert puntajes["a"] == pytest.approx(1 / 61) and puntajes["c"] == pytest.approx(1 / 63)
    assert dict((c, f) for c, _, f in r)["b"] == ("sem", "lex")


def test_rrf_premia_el_consenso_sobre_un_primer_puesto_aislado():
    r = fusionar_rrf({"sem": ["solo_sem", "comun"], "lex": ["solo_lex", "comun"], "cod": ["otro", "comun"]})
    assert r[0][0] == "comun"


def test_rrf_con_pesos_y_sin_repetidos():
    r = fusionar_rrf({"sem": ["a", "a", "b"], "lex": ["b"]}, k=10, pesos={"sem": 2.0})
    puntajes = {c: p for c, p, _ in r}
    assert puntajes["a"] == pytest.approx(2 / 11) and puntajes["b"] == pytest.approx(2 / 12 + 1 / 11)


def test_rrf_empates_comparten_posicion():
    """La lista de códigos usa rank(): dos secciones con el mismo puntaje reciben lo mismo."""
    r = fusionar_rrf({"cod": [Candidato("a", 1, 4.0), Candidato("b", 1, 4.0), Candidato("c", 3, 1.0)]}, k=60)
    puntajes = {c: p for c, p, _ in r}
    assert puntajes["a"] == puntajes["b"] == pytest.approx(1 / 61) and puntajes["c"] == pytest.approx(1 / 63)


def test_rrf_desempata_por_mejor_posicion_y_cita():
    r = fusionar_rrf({"sem": ["x", "y"], "lex": ["y", "x"]})
    assert [c for c, _, _ in r] == ["x", "y"]
    assert fusionar_rrf({}) == []


def test_combinacion_convexa_normaliza_cada_lista():
    sem = [Candidato("a", 1, 0.90), Candidato("b", 2, 0.85), Candidato("c", 3, 0.80)]
    lex = [Candidato("b", 1, 12.0), Candidato("d", 2, 3.0)]
    r = fusionar_cc({"sem": sem, "lex": lex}, pesos={"sem": 0.4, "lex": 0.6})
    puntajes = {c: p for c, p, _ in r}
    assert [c for c, _, _ in r] == ["b", "a", "d", "c"]  # c y d empatan en 0: gana la mejor posición
    assert puntajes["b"] == pytest.approx(0.4 * 0.5 + 0.6 * 1.0) and puntajes["a"] == pytest.approx(0.4)
    assert puntajes["c"] == puntajes["d"] == 0.0  # el último de cada lista vale lo mismo que no estar
    assert dict((c, f) for c, _, f in r)["b"] == ("sem", "lex")


def test_combinacion_convexa_con_un_solo_candidato_y_listas_vacias():
    r = fusionar_cc({"sem": [], "cod": [Candidato("x", 1, 3.0)]}, pesos={"sem": 0.4, "cod": 0.2})
    assert r == [("x", 0.2, ("cod",))]
    assert fusionar_cc({}) == []


def test_el_buscador_usa_la_fusion_pedida():
    listas = {"sem": [Candidato("a", 1, 0.9), Candidato("c", 2, 0.5)],
              "lex": [Candidato("b", 1, 5.0), Candidato("c", 2, 1.0)]}
    assert BuscadorManuales("postgresql://x").fusionar(listas)[0][0] == "b"  # cc: el 1.º léxico pesa 0,6
    assert BuscadorManuales("postgresql://x", fusion="rrf").fusionar(listas)[0][0] == "c"  # rrf: el consenso


def test_filtro_por_defecto_vigente_y_aplicable():
    where, params = condiciones(Filtros())
    assert where == "vigente AND aplica_pia3" and params == {}


def test_filtros_del_pedido():
    where, params = condiciones(Filtros(documentos=("TX350-D", "MBP-4"), equipo="B-102", tipos_documento=("contrato",)))
    assert "documento = ANY(%(f_documentos)s)" in where and "tipo_documento = ANY(%(f_tipos)s)" in where
    assert "'PLANTA' = ANY(equipos)" in where  # las órdenes generales cuentan para todos los equipos
    assert params == {"f_documentos": ["TX350-D", "MBP-4"], "f_equipo": "B-102", "f_tipos": ["contrato"]}
    assert condiciones(Filtros(incluir_no_vigentes=True, incluir_no_aplicables=True))[0] == "true"
    assert condiciones(Filtros(incluir_no_vigentes=True))[0] == "aplica_pia3"


def test_el_filtro_va_dentro_de_cada_lista_antes_del_limit():
    """Pre-filtering: el WHERE está en cada una de las tres búsquedas, antes de su LIMIT."""
    sql = sql_listas(("sem", "lex", "cod"), "vigente AND aplica_pia3")
    assert sql.count("vigente AND aplica_pia3") == 3
    for parte in sql.split("UNION ALL"):
        assert parte.index("vigente AND aplica_pia3") < parte.index("LIMIT %(n)s")
    assert "'sem'" not in sql_listas(("lex", "cod"), "true") and "'cod'" not in sql_listas(("sem",), "true")


def test_recortar_en_palabra():
    assert recortar("corto", 100) == "corto"
    t = recortar("palabra " * 200, 50)
    assert t.endswith(" …") and len(t) <= 52 and "palabr " not in t


def test_modo_segun_las_listas():
    assert BuscadorManuales("postgresql://x", listas=("sem", "lex", "cod")).modo == "hibrida"
    assert BuscadorManuales("postgresql://x", listas=("sem",)).modo == "vectores"
    sin_modelo = BuscadorManuales("postgresql://x")
    sin_modelo._sin_modelo = True
    assert sin_modelo.modo == "lexica"


async def test_si_el_modelo_no_carga_sigue_con_la_lexica():
    class EmbedderRoto(Embedder):
        def consulta(self, texto):
            raise RuntimeError("sin modelo")

    b = BuscadorManuales("postgresql://x", embedder=EmbedderRoto("e5-small-int8"))
    assert await b._vector("pregunta") is None
    assert b.modo == "lexica"


def test_prefijos_de_e5_en_consulta_y_pasajes():
    class MotorFalso:
        def __init__(self):
            self.textos = []

        def embed(self, textos, batch_size=None):
            self.textos += list(textos)
            return [np.array([3.0, 4.0]) for _ in textos]

    e = Embedder("e5-small-int8")
    e._motor = MotorFalso()
    v = e.consulta("¿qué aceite lleva?")
    assert np.allclose(v, [0.6, 0.8])  # normalizado
    e.consulta("¿qué aceite lleva?")  # sale del cache
    e.pasajes(["3.8 Lubricantes aprobados"])
    assert e._motor.textos == ["query: ¿qué aceite lleva?", "passage: 3.8 Lubricantes aprobados"]


def test_vectores_precalculados_ida_y_vuelta(tmp_path):
    ruta = tmp_path / "v.npz"
    np.savez_compressed(ruta, citas=np.array(["A §1", "B §2"]), vectores=np.eye(2, dtype=np.float32),
                        modelo=np.array("e5-small-int8"), huella=np.array("abc"))
    v = leer_vectores(ruta)
    assert isinstance(v, VectoresCorpus) and v.citas == ["A §1", "B §2"] and v.huella == "abc"
    assert np.allclose(v.por_cita()["B §2"], [0, 1])
    assert leer_vectores(tmp_path / "no-existe.npz") is None
