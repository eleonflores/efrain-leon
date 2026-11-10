import pytest

from apoyo_herramientas import recursos
from sistema.herramientas import Recursos, ejecutar
from sistema.rag.busqueda import ErrorRag, Filtros, Fragmento


def _fragmento(cita: str, documento: str = "TX350-D") -> Fragmento:
    return Fragmento(cita=cita, documento=documento, revision="D", seccion=cita.split("§")[-1], titulo="Título",
                     pagina=12, fabricante="Trimax Industrial S.A.", equipos=("B-101",), vigente=True,
                     texto="Texto de la sección", puntaje=0.0328)


class BuscadorFalso:
    modo = "hibrida"

    def __init__(self, fragmentos=None, error=None):
        self.fragmentos = fragmentos if fragmentos is not None else [_fragmento("TX350-D §8.9"),
                                                                     _fragmento("MBP-4 §6.11", "MBP-4")]
        self.error = error
        self.pedidos: list[tuple[str, int, Filtros]] = []

    async def buscar(self, pregunta, k=5, filtros=None):
        self.pedidos.append((pregunta, k, filtros))
        if self.error:
            raise self.error
        return self.fragmentos[:k]


def _recursos(buscador) -> Recursos:
    r = recursos()
    r.manuales = buscador
    return r


async def test_devuelve_fragmentos_con_sus_citas():
    b = BuscadorFalso()
    salida = await ejecutar("buscar_en_manuales", {"pregunta": "la bomba hace ruido a piedras"}, _recursos(b))
    assert salida.citas == ["TX350-D §8.9", "MBP-4 §6.11"]
    assert salida.fragmentos[0].cita == "TX350-D §8.9" and salida.fragmentos[0].pagina == 12
    assert salida.modo == "hibrida" and salida.observacion is None
    pregunta, k, filtros = b.pedidos[0]
    assert k == 4 and filtros == Filtros()  # solo vigente y aplicable a PIA-3


async def test_filtros_de_documento_y_equipo_por_nombre_de_campo():
    b = BuscadorFalso()
    await ejecutar("buscar_en_manuales", {"pregunta": "qué se encontró antes", "documento": "historial",
                                          "equipo": "la dos", "k": 6}, _recursos(b))
    _, k, filtros = b.pedidos[0]
    assert k == 6 and filtros.documentos == ("historial",) and filtros.equipo == "B-102"
    assert not filtros.incluir_no_vigentes and not filtros.incluir_no_aplicables


@pytest.mark.parametrize("argumentos, codigo, pista", [
    ({"incluir_rev_c": True}, "ARGUMENTOS_INVALIDOS", "incluir_rev_c"),
    ({"documento": "TX350-C"}, "ARGUMENTOS_INVALIDOS", "TX350-D"),
    ({"equipo": "B-104"}, "EQUIPO_INEXISTENTE", "B-101"),
])
async def test_no_se_puede_pedir_la_rev_c_ni_un_equipo_inexistente(argumentos, codigo, pista):
    b = BuscadorFalso()
    salida = await ejecutar("buscar_en_manuales", {"pregunta": "límites", **argumentos}, _recursos(b))
    assert salida.codigo == codigo and pista in salida.mensaje and not salida.reintentable
    assert b.pedidos == []


async def test_base_caida_es_reintentable():
    b = BuscadorFalso(error=ErrorRag("La base del RAG no está disponible"))
    salida = await ejecutar("buscar_en_manuales", {"pregunta": "algo"}, _recursos(b))
    assert salida.codigo == "RAG_NO_DISPONIBLE" and salida.reintentable


async def test_recuerda_que_limites_y_stock_no_salen_de_los_manuales():
    r = _recursos(BuscadorFalso())
    limites = await ejecutar("buscar_en_manuales", {"pregunta": "¿a qué vibración dispara la bomba?"}, r)
    assert "consultar_equipos" in limites.observacion
    stock = await ejecutar("buscar_en_manuales", {"pregunta": "¿cuántos cartuchos hay en el almacén?"}, r)
    assert "consultar_repuestos" in stock.observacion
    vacio = await ejecutar("buscar_en_manuales", {"pregunta": "algo raro"}, _recursos(BuscadorFalso([])))
    assert vacio.citas == [] and "otras palabras" in vacio.observacion
