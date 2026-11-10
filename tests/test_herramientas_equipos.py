import pytest

from apoyo_herramientas import recursos, simular_planta
from sistema.herramientas import ErrorHerramienta, ejecutar
from sistema.herramientas.modelos import SalidaEquipos


@pytest.fixture
def api():
    with simular_planta() as m:
        yield m


async def test_todos_los_equipos(api):
    salida = await ejecutar("consultar_equipos", {}, recursos())
    assert isinstance(salida, SalidaEquipos)
    assert [e.tag for e in salida.equipos] == ["B-101", "B-102", "B-103", "F-201A", "F-201B", "TK-301", "FT-401"]


async def test_por_nombre_informal(api):
    salida = await ejecutar("consultar_equipos", {"tag": "la dos"}, recursos())
    (b102,) = salida.equipos
    assert b102.tag == "B-102" and b102.unidad_manometro_local == "psi" and b102.modelo == "TX-350"
    descarga = next(s for s in b102.sensores if s.variable == "presion_descarga")
    assert (descarga.alarma_baja, descarga.alarma_alta) == (95, 125)
    assert "presion_descarga_local" in b102.lecturas_locales


async def test_tag_sin_guion_ni_mayusculas(api):
    salida = await ejecutar("consultar_equipos", {"tag": "b103"}, recursos())
    assert [e.tag for e in salida.equipos] == ["B-103"]


async def test_por_tipo(api):
    salida = await ejecutar("consultar_equipos", {"tipo": "filtro"}, recursos())
    assert [e.tag for e in salida.equipos] == ["F-201A", "F-201B"]
    assert all(e.sensores[0].variable == "presion_diferencial" for e in salida.equipos)


async def test_equipo_inexistente_dice_cuales_hay(api):
    salida = await ejecutar("consultar_equipos", {"tag": "B-104"}, recursos())
    assert isinstance(salida, ErrorHerramienta)
    assert salida.codigo == "EQUIPO_INEXISTENTE" and not salida.reintentable
    assert "B-104" in salida.mensaje and "B-101" in salida.mensaje and "FT-401" in salida.mensaje
