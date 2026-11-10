import pytest

from apoyo_herramientas import recursos, simular_planta
from sistema.herramientas import ErrorHerramienta, ejecutar
from sistema.herramientas.materiales import MaterialesYaml
from sistema.herramientas.modelos import SalidaRepuestos, SalidaTareas


@pytest.fixture
def api():
    with simular_planta() as m:
        yield m


async def test_catalogo_ausente_da_error_estructurado(tmp_path):
    r = recursos()
    r.materiales = MaterialesYaml(tmp_path / "no-esta.yaml")
    salida = await ejecutar("consultar_repuestos", {}, r)
    assert salida.codigo == "MATERIALES_NO_DISPONIBLES" and "MATERIALES_PATH" in salida.mensaje


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


@pytest.mark.parametrize("argumentos, codigo, pista", [
    ({"codigo": "XX-999"}, "REPUESTO_INEXISTENTE", "INS-TRANS-P"),
    ({"equipo": "B-102", "codigo": "TX-EMP-KIT"}, "ARGUMENTOS_INVALIDOS", "no los dos"),
    ({"codigo": "kit de empaquetadura"}, "ARGUMENTOS_INVALIDOS", "codigo"),
])
async def test_repuestos_validacion(api, argumentos, codigo, pista):
    salida = await ejecutar("consultar_repuestos", argumentos, recursos())
    assert isinstance(salida, ErrorHerramienta) and salida.codigo == codigo and not salida.reintentable
    assert pista in salida.mensaje


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
])
async def test_tareas_validacion(api, argumentos, codigo, pista):
    salida = await ejecutar("consultar_tareas", argumentos, recursos())
    assert isinstance(salida, ErrorHerramienta) and salida.codigo == codigo and pista in salida.mensaje
