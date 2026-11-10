"""consultar_repuestos y consultar_tareas: inventario, listas de materiales y catálogo, leídos de materiales.yaml."""

import pytest

from apoyo_herramientas import DATOS, recursos, simular_planta
from sistema.herramientas import ErrorHerramienta, ejecutar
from sistema.herramientas.materiales import MaterialesYaml, ruta_materiales
from sistema.herramientas.modelos import SalidaRepuestos, SalidaTareas


@pytest.fixture
def api():
    """Solo hace falta para nombres informales; con TAG exacto no se consulta la planta."""
    with simular_planta() as m:
        yield m


# ---------------------------------------------------------------- repositorio

async def test_repositorio_yaml(materiales):
    catalogo = await MaterialesYaml(DATOS / "materiales.yaml").cargar()
    assert set(catalogo.repuestos) == {r["codigo"] for r in materiales["repuestos"]}
    assert catalogo.lista_materiales["F-201B"] == ["FC-CART-10", "FC-JUNTA-TAPA", "INS-TRANS-P"]
    assert sum(not t.estandar for t in catalogo.tareas) == len(materiales["tareas_no_estandar"])


def test_ruta_por_variable_de_entorno(monkeypatch, tmp_path):
    monkeypatch.setenv("MATERIALES_PATH", str(tmp_path / "m.yaml"))
    assert ruta_materiales() == tmp_path / "m.yaml"
    monkeypatch.delenv("MATERIALES_PATH")
    assert ruta_materiales().name == "materiales.yaml" and ruta_materiales().exists()


async def test_catalogo_ausente_da_error_estructurado(tmp_path):
    r = recursos()
    r.materiales = MaterialesYaml(tmp_path / "no-esta.yaml")
    salida = await ejecutar("consultar_repuestos", {}, r)
    assert salida.codigo == "MATERIALES_NO_DISPONIBLES" and "MATERIALES_PATH" in salida.mensaje


# ---------------------------------------------------------------- consultar_repuestos

async def test_inventario_completo(api):
    salida = await ejecutar("consultar_repuestos", {}, recursos())
    assert isinstance(salida, SalidaRepuestos) and len(salida.repuestos) == 11
    assert not api["planta"].called


async def test_lista_de_materiales_de_un_equipo(api):
    salida = await ejecutar("consultar_repuestos", {"equipo": "B-102"}, recursos())
    assert salida.equipo == "B-102" and len(salida.repuestos) == 8
    kit = next(r for r in salida.repuestos if r.codigo == "TX-EMP-KIT")
    assert (kit.costo_unitario_usd, kit.stock_yacimiento, kit.stock_central) == (420, 3, 12)
    assert not api["planta"].called


async def test_por_codigo(api):
    salida = await ejecutar("consultar_repuestos", {"codigo": "tx-rod-cig"}, recursos())
    (rod,) = salida.repuestos
    assert rod.codigo == "TX-ROD-CIG" and rod.stock_yacimiento == 0 and rod.stock_central == 2
    assert rod.equipos == ["B-101", "B-102", "B-103"]


async def test_equipo_por_nombre_informal_sin_lista(api):
    salida = await ejecutar("consultar_repuestos", {"equipo": "el pulmón"}, recursos())
    assert salida.equipo == "TK-301" and salida.repuestos == [] and "no tiene lista" in salida.observacion


@pytest.mark.parametrize("argumentos, codigo", [
    ({"codigo": "XX-999"}, "REPUESTO_INEXISTENTE"),
    ({"equipo": "B-104"}, "EQUIPO_INEXISTENTE"),
    ({"equipo": "B-102", "codigo": "TX-EMP-KIT"}, "ARGUMENTOS_INVALIDOS"),
    ({"codigo": "kit de empaquetadura"}, "ARGUMENTOS_INVALIDOS"),
    ({"almacen": "central"}, "ARGUMENTOS_INVALIDOS"),
])
async def test_repuestos_validacion(api, argumentos, codigo):
    salida = await ejecutar("consultar_repuestos", argumentos, recursos())
    assert isinstance(salida, ErrorHerramienta) and salida.codigo == codigo and not salida.reintentable


async def test_repuesto_inexistente_lista_los_validos(api):
    salida = await ejecutar("consultar_repuestos", {"codigo": "XX-999"}, recursos())
    assert "TX-EMP-KIT" in salida.mensaje and "INS-TRANS-P" in salida.mensaje


# ---------------------------------------------------------------- consultar_tareas

async def test_tareas_de_un_filtro_con_costo_y_stock(api):
    salida = await ejecutar("consultar_tareas", {"equipo": "el filtro B"}, recursos())
    assert isinstance(salida, SalidaTareas) and salida.equipo == "F-201B"
    cartuchos = next(t for t in salida.tareas if t.codigo == "T-F-CAR")
    assert cartuchos.equipos == ["F-201B"] and not cartuchos.detiene_equipo and cartuchos.ejecutor == "propio"
    (rep,) = cartuchos.repuestos
    assert (rep.codigo, rep.cantidad, rep.costo_usd) == ("FC-CART-10", 48, 816)
    assert rep.alcanza_stock_yacimiento is False                      # hay 40 en el yacimiento
    assert cartuchos.costo_total_usd == 816
    calibracion = next(t for t in salida.tareas if t.codigo == "T-I-CAL")
    assert calibracion.repuestos == [] and calibracion.costo_total_usd == 0


async def test_tareas_de_una_bomba_incluyen_las_no_estandar(api):
    salida = await ejecutar("consultar_tareas", {"equipo": "B-102"}, recursos())
    estandar = [t.codigo for t in salida.tareas if t.estandar]
    no_estandar = [t.codigo for t in salida.tareas if not t.estandar]
    assert estandar == ["T-B-EMP", "T-B-VAL", "T-B-ACE", "T-B-COR", "T-I-CAL"]
    assert no_estandar == ["T-B-ROD", "T-B-ALI", "I-VIB", "I-VAL"]


async def test_tarea_no_estandar_sin_costo_conocido(api):
    salida = await ejecutar("consultar_tareas", {"codigo": "T-B-ROD"}, recursos())
    (rod,) = salida.tareas
    assert not rod.estandar and rod.ejecutor == "contratista" and rod.detiene_equipo and rod.horas == 16
    assert rod.repuestos is None and rod.costo_total_usd is None


async def test_codigo_con_variantes_por_equipo(api):
    salida = await ejecutar("consultar_tareas", {"codigo": "T-F-CAR"}, recursos())
    assert [t.equipos for t in salida.tareas] == [["F-201A"], ["F-201B"]]


async def test_solo_no_estandar(api):
    salida = await ejecutar("consultar_tareas", {"estandar": False}, recursos())
    assert {t.codigo for t in salida.tareas} == {"T-B-ROD", "T-B-ALI", "I-VIB", "I-VAL"}


@pytest.mark.parametrize("argumentos, codigo, pista", [
    ({"codigo": "T-X-999"}, "TAREA_INEXISTENTE", "T-B-EMP"),
    ({"equipo": "B-104"}, "EQUIPO_INEXISTENTE", "B-101"),
    ({"estandar": "quizás"}, "ARGUMENTOS_INVALIDOS", "estandar"),
    ({"equipo": "B-102", "urgente": True}, "ARGUMENTOS_INVALIDOS", "'urgente' no existe"),
])
async def test_tareas_validacion(api, argumentos, codigo, pista):
    salida = await ejecutar("consultar_tareas", argumentos, recursos())
    assert isinstance(salida, ErrorHerramienta) and salida.codigo == codigo and pista in salida.mensaje
