"""consultar_historial_ordenes: órdenes reales de B-102, de la más nueva a la más vieja y acotadas."""

import httpx
import pytest

from apoyo_herramientas import dato, recursos, simular_planta
from sistema.herramientas import ErrorHerramienta, ejecutar
from sistema.herramientas.modelos import SalidaHistorialOrdenes

RUTA = "/api/historial-ordenes"


@pytest.fixture
def api():
    with simular_planta() as m:
        m.get(RUTA, name="ordenes").respond(json=dato("api_historial_ordenes_B-102.json"))
        yield m


async def test_mas_nuevas_primero(api):
    salida = await ejecutar("consultar_historial_ordenes", {"equipo": "la dos", "limite": 3}, recursos())
    assert isinstance(salida, SalidaHistorialOrdenes)
    assert salida.equipo == "B-102" and salida.total == 8 and salida.devueltas == 3
    assert [o.id for o in salida.ordenes] == ["OT-H-0003", "OT-26-0087", "OT-26-0086"]
    assert api["ordenes"].calls.last.request.url.params["equipo"] == "B-102"


async def test_campos_de_texto_libre_y_repuestos(api):
    salida = await ejecutar("consultar_historial_ordenes", {"equipo": "B-102", "tarea": "t-b-val"}, recursos())
    (orden,) = salida.ordenes
    assert orden.id == "OT-26-0087" and orden.tipo == "correctiva" and orden.horas == 5.0
    assert "golpea" in orden.aviso and orden.repuestos[0].codigo == "TX-VAL-KIT"
    assert orden.fecha.isoformat() == "2026-10-06T11:20:00-03:00"    # la API la manda sin segundos


async def test_orden_del_simulador_con_menos_campos(api):
    salida = await ejecutar("consultar_historial_ordenes", {"equipo": "B-102", "limite": 1}, recursos())
    (orden,) = salida.ordenes
    assert orden.origen == "simulador" and orden.descripcion == "Corrección de falla F01" and orden.aviso is None


async def test_filtro_por_tarea_cuenta_el_total(api):
    salida = await ejecutar("consultar_historial_ordenes", {"equipo": "B-102", "tarea": "T-B-COR", "limite": 1},
                            recursos())
    assert salida.total == 3 and salida.devueltas == 1 and salida.ordenes[0].id == "OT-26-0086"


async def test_rango_de_fechas(api):
    argumentos = {"equipo": "B-102", "desde": "2026-09-16T00:00:00-03:00", "hasta": "2026-09-30T00:00:00-03:00"}
    salida = await ejecutar("consultar_historial_ordenes", argumentos, recursos())
    assert [o.id for o in salida.ordenes] == ["OT-26-0085", "OT-26-0084", "OT-26-0082"]
    assert api["ordenes"].calls.last.request.url.params["desde"] == "2026-09-16T00:00:00-03:00"


async def test_ordenes_generales_de_planta(api):
    api["ordenes"].respond(json=[])
    salida = await ejecutar("consultar_historial_ordenes", {"equipo": "planta"}, recursos())
    assert salida.equipo == "PLANTA" and salida.total == 0
    assert api["ordenes"].calls.last.request.url.params["equipo"] == "PLANTA"


async def test_orden_mal_formada_se_descarta(api):
    ordenes = dato("api_historial_ordenes_B-102.json")
    ordenes[0]["fecha"] = "sin fecha"
    api["ordenes"].respond(json=ordenes)
    salida = await ejecutar("consultar_historial_ordenes", {"equipo": "B-102"}, recursos())
    assert salida.total == 7


@pytest.mark.parametrize("argumentos, codigo", [
    ({"equipo": "B-104"}, "EQUIPO_INEXISTENTE"),
    ({"equipo": "B-102", "limite": 0}, "ARGUMENTOS_INVALIDOS"),
    ({"equipo": "B-102", "limite": 500}, "ARGUMENTOS_INVALIDOS"),
    ({"equipo": "B-102", "tarea": "cambio de correas"}, "ARGUMENTOS_INVALIDOS"),
    ({"equipo": "B-102", "desde": "2026-10-01T00:00:00-03:00", "hasta": "2026-09-01T00:00:00-03:00"},
     "ARGUMENTOS_INVALIDOS"),
    ({"equipo": "B-102", "estado": "Cerrada"}, "ARGUMENTOS_INVALIDOS"),
])
async def test_validacion(api, argumentos, codigo):
    salida = await ejecutar("consultar_historial_ordenes", argumentos, recursos())
    assert isinstance(salida, ErrorHerramienta) and salida.codigo == codigo and not salida.reintentable
    assert not api["ordenes"].called


async def test_conexion_caida(api):
    api["ordenes"].mock(side_effect=httpx.ConnectError("sin ruta"))
    salida = await ejecutar("consultar_historial_ordenes", {"equipo": "B-102"}, recursos())
    assert salida.codigo == "PLANTA_NO_DISPONIBLE" and salida.reintentable
    assert api["ordenes"].call_count == 3
