from datetime import datetime, timezone

import httpx
import pytest
import respx

from apoyo_herramientas import URL, dato
from sistema.integraciones.planta_api import ClientePlanta, ErrorPlanta


def cliente() -> ClientePlanta:
    return ClientePlanta(URL, timeout_s=0.5, reintentos=2, backoff_s=0)


async def test_reintenta_ante_5xx_y_sale_bien():
    with respx.mock(base_url=URL) as m:
        ruta = m.get("/api/planta").mock(side_effect=[httpx.Response(503), httpx.Response(502),
                                                       httpx.Response(200, json=dato("api_planta.json"))])
        definicion = await cliente().definicion()
    assert ruta.call_count == 3
    assert {e["tag"] for e in definicion["equipos"]} >= {"B-101", "F-201B", "FT-401"}


@pytest.mark.parametrize("falla, codigo", [
    (httpx.ReadTimeout("lento"), "PLANTA_TIMEOUT"),
    (httpx.ConnectError("rechazada"), "PLANTA_NO_DISPONIBLE"),
    (httpx.Response(500), "PLANTA_NO_DISPONIBLE"),
])
async def test_falla_transitoria_persistente_da_error_reintentable(falla, codigo):
    with respx.mock(base_url=URL) as m:
        ruta = m.get("/api/planta")
        ruta.mock(return_value=falla) if isinstance(falla, httpx.Response) else ruta.mock(side_effect=falla)
        with pytest.raises(ErrorPlanta) as e:
            await cliente().definicion()
    assert ruta.call_count == 3
    assert e.value.codigo == codigo and e.value.reintentable
    assert "3 intentos" in e.value.mensaje


async def test_4xx_no_se_reintenta():
    with respx.mock(base_url=URL) as m:
        ruta = m.get("/api/historian/B-102/presion_descarga").respond(422, json={"detail": "fecha inválida"})
        with pytest.raises(ErrorPlanta) as e:
            await cliente().historian("B-102", "presion_descarga", datetime(2026, 11, 10))
    assert ruta.call_count == 1
    assert e.value.codigo == "PLANTA_RECHAZO" and not e.value.reintentable


async def test_respuesta_que_no_es_json():
    with respx.mock(base_url=URL) as m:
        m.get("/api/historial-ordenes").respond(200, text="<html>proxy</html>")
        with pytest.raises(ErrorPlanta) as e:
            await cliente().historial_ordenes("B-102")
    assert e.value.codigo == "RESPUESTA_INVALIDA" and not e.value.reintentable


async def test_la_definicion_se_pide_una_sola_vez():
    c = cliente()
    with respx.mock(base_url=URL) as m:
        ruta = m.get("/api/planta").respond(json=dato("api_planta.json"))
        await c.definicion()
        await c.definicion()
    assert ruta.call_count == 1


async def test_fechas_viajan_en_hora_de_planta():
    with respx.mock(base_url=URL) as m:
        ruta = m.get("/api/historian/B-102/vibracion").respond(json=[])
        await cliente().historian("B-102", "vibracion", datetime(2026, 11, 10, 10, 0, tzinfo=timezone.utc),
                                  datetime(2026, 11, 10, 12, 30, 15, 500))
    params = ruta.calls.last.request.url.params
    assert params["desde"] == "2026-11-10T07:00:00-03:00"
    assert params["hasta"] == "2026-11-10T12:30:15-03:00"    # sin offset: se toma como hora de planta
