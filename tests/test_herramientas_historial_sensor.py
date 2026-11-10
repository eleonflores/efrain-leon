"""consultar_historial_sensor: resumen y serie acotada, validación semántica y fallas del historiador."""

import json
from datetime import datetime, timedelta

import httpx
import pytest

from apoyo_herramientas import dato, recursos, simular_planta
from sistema.herramientas import ErrorHerramienta, ejecutar
from sistema.herramientas.modelos import SalidaHistorialSensor
from sistema.integraciones.planta_api import ZONA_PLANTA

RUTA = "/api/historian/B-102/presion_descarga"
DOS_HORAS = {"tag": "B-102", "variable": "presion_descarga", "desde": "2026-11-10T05:00:00-03:00",
             "hasta": "2026-11-10T06:59:00-03:00"}


@pytest.fixture
def api():
    with simular_planta() as m:
        m.get(RUTA, name="historian").respond(json=dato("api_historian_B-102_presion_descarga.json"))
        yield m


def serie_sintetica(minutos: int, valor=lambda i: 110 + (i % 7)) -> list[dict]:
    inicio = datetime(2026, 9, 26, 7, 0, tzinfo=ZONA_PLANTA)
    return [{"ts": (inicio + timedelta(minutes=i)).isoformat(), "valor": valor(i)} for i in range(minutos)]


async def test_resumen_de_dos_horas_reales(api):
    crudos = dato("api_historian_B-102_presion_descarga.json")
    valores = [p["valor"] for p in crudos]
    salida = await ejecutar("consultar_historial_sensor", DOS_HORAS, recursos())
    assert isinstance(salida, SalidaHistorialSensor)
    r = salida.resumen
    assert r.n_muestras == 120 and r.n_sin_valor == 0
    assert (r.minimo, r.maximo) == (min(valores), max(valores))
    assert r.promedio == pytest.approx(sum(valores) / len(valores), abs=1e-3)
    assert r.minimo <= r.p5 <= r.p95 <= r.maximo
    assert r.ultimo_ts.isoformat() == "2026-11-10T06:59:00-03:00" and r.ultimo_valor == valores[-1]
    assert (salida.limites.alarma_baja, salida.limites.alarma_alta) == (95, 125)
    assert salida.unidad == "kg/cm2"
    assert len(salida.serie) == 24 and salida.minutos_por_punto == 5
    assert salida.serie[0].ts.isoformat() == "2026-11-10T05:00:00-03:00"
    assert salida.serie[0].valor == pytest.approx(sum(valores[:5]) / 5, abs=1e-3)


async def test_salida_acotada_con_45_dias(api):
    api["historian"].respond(json=serie_sintetica(45 * 24 * 60))
    argumentos = {"tag": "la dos", "variable": "presion_descarga", "desde": "2026-09-26T07:00:00-03:00"}
    salida = await ejecutar("consultar_historial_sensor", argumentos, recursos())
    assert salida.resumen.n_muestras == 64800
    assert len(salida.serie) <= 24
    assert len(salida.model_dump_json()) < 4000


async def test_menos_muestras_que_max_puntos_devuelve_todas(api):
    salida = await ejecutar("consultar_historial_sensor", {**DOS_HORAS, "max_puntos": 200}, recursos())
    assert len(salida.serie) == 120 and salida.minutos_por_punto == 1


async def test_valores_nulos_y_alarmas(api):
    api["historian"].respond(json=serie_sintetica(10, lambda i: None if i < 4 else 120 + i))   # 124..129
    salida = await ejecutar("consultar_historial_sensor", {**DOS_HORAS, "desde": "2026-09-26T07:00:00-03:00",
                                                           "hasta": None, "max_puntos": 2}, recursos())
    r = salida.resumen
    assert r.n_muestras == 10 and r.n_sin_valor == 4
    assert (r.minimo, r.maximo) == (124, 129) and r.muestras_sobre_alarma_alta == 5
    assert [p.valor for p in salida.serie] == [124.0, 127.0]     # tramos de 5: [None×4, 124] y [125..129]


async def test_tramo_sin_datos_queda_en_null(api):
    api["historian"].respond(json=serie_sintetica(4, lambda i: None if i < 2 else 1.5))
    salida = await ejecutar("consultar_historial_sensor", {**DOS_HORAS, "desde": "2026-09-26T07:00:00-03:00",
                                                           "hasta": None, "max_puntos": 2}, recursos())
    assert [p.valor for p in salida.serie] == [None, 1.5]
    assert salida.resumen.ultimo_valor == 1.5


async def test_sin_muestras_explica_por_que(api):
    api["historian"].respond(json=[])
    salida = await ejecutar("consultar_historial_sensor", DOS_HORAS, recursos())
    assert salida.resumen.n_muestras == 0 and salida.serie == []
    assert "45 días" in salida.observacion


async def test_descarta_muestras_fuera_del_rango(api):
    api["historian"].respond(json=serie_sintetica(30))           # 07:00 a 07:29
    argumentos = {**DOS_HORAS, "desde": "2026-09-26T07:10:00-03:00", "hasta": "2026-09-26T07:19:00-03:00"}
    salida = await ejecutar("consultar_historial_sensor", argumentos, recursos())
    assert salida.resumen.n_muestras == 10


async def test_rango_en_utc_se_pide_en_hora_de_planta(api):
    await ejecutar("consultar_historial_sensor", {**DOS_HORAS, "desde": "2026-11-10T08:00:00Z",
                                                  "hasta": "2026-11-10T09:59:00Z"}, recursos())
    params = api["historian"].calls.last.request.url.params
    assert (params["desde"], params["hasta"]) == ("2026-11-10T05:00:00-03:00", "2026-11-10T06:59:00-03:00")


@pytest.mark.parametrize("cambios, codigo, pista", [
    ({"tag": "B-104"}, "EQUIPO_INEXISTENTE", "B-101"),
    ({"tag": "la bomba"}, "EQUIPO_INEXISTENTE", "TAG exacto"),
    ({"variable": "presion_diferencial"}, "SENSOR_INEXISTENTE", "presion_succion, presion_descarga"),
    ({"tag": "TK-301", "variable": "caudal"}, "SENSOR_INEXISTENTE", "lecturas de la recorrida"),
    ({"variable": "temperatura_rodamiento_ir"}, "ARGUMENTOS_INVALIDOS", "valores permitidos"),
    ({"desde": "2026-11-10T07:00:00-03:00"}, "ARGUMENTOS_INVALIDOS", "anterior a 'hasta'"),
    ({"desde": "ayer"}, "ARGUMENTOS_INVALIDOS", "ISO 8601"),
    ({"desde": None}, "ARGUMENTOS_INVALIDOS", "desde"),
    ({"max_puntos": 5000}, "ARGUMENTOS_INVALIDOS", "max_puntos"),
    ({"limite": 3}, "ARGUMENTOS_INVALIDOS", "'limite' no existe"),
])
async def test_validacion_antes_de_consultar_el_historiador(api, cambios, codigo, pista):
    salida = await ejecutar("consultar_historial_sensor", {**DOS_HORAS, **cambios}, recursos())
    assert isinstance(salida, ErrorHerramienta)
    assert salida.codigo == codigo and not salida.reintentable and pista in salida.mensaje
    assert not api["historian"].called


async def test_falta_desde(api):
    argumentos = {k: v for k, v in DOS_HORAS.items() if k != "desde"}
    salida = await ejecutar("consultar_historial_sensor", argumentos, recursos())
    assert salida.codigo == "ARGUMENTOS_INVALIDOS" and "falta el campo obligatorio 'desde'" in salida.mensaje


async def test_historiador_lento_reintenta_y_devuelve_error_estructurado(api):
    api["historian"].mock(side_effect=httpx.ReadTimeout("lento"))
    salida = await ejecutar("consultar_historial_sensor", DOS_HORAS, recursos())
    assert api["historian"].call_count == 3
    assert json.loads(salida.model_dump_json()) == {"codigo": "PLANTA_TIMEOUT", "mensaje": salida.mensaje,
                                                    "reintentable": True}


async def test_historiador_se_recupera_al_segundo_intento(api):
    api["historian"].mock(side_effect=[httpx.Response(503),
                                       httpx.Response(200, json=dato("api_historian_B-102_presion_descarga.json"))])
    salida = await ejecutar("consultar_historial_sensor", DOS_HORAS, recursos())
    assert isinstance(salida, SalidaHistorialSensor) and salida.resumen.n_muestras == 120
