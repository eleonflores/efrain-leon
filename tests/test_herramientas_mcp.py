import asyncio
import json

import pytest
from langchain_core.messages import ToolMessage
from mcp import Client
from mcp.shared.exceptions import MCPError
from starlette.testclient import TestClient

from apoyo_herramientas import recursos, simular_planta
from sistema.herramientas import HERRAMIENTAS, Recursos, ejecutar, herramientas_langchain
from sistema.herramientas.servidor_mcp import crear_app, crear_servidor
from sistema.integraciones.planta_api import ClientePlanta

NOMBRES = ["consultar_equipos", "consultar_historial_sensor", "consultar_historial_ordenes", "consultar_repuestos",
           "consultar_tareas", "buscar_en_manuales"]


@pytest.fixture
def api():
    with simular_planta() as m:
        yield m


def test_contratos_estrictos_y_descripciones_completas():
    assert list(HERRAMIENTAS) == NOMBRES
    for h in HERRAMIENTAS.values():
        assert h.entrada.model_json_schema()["additionalProperties"] is False
        assert h.salida.model_json_schema()["additionalProperties"] is False
        assert "Usala para" in h.descripcion and "Solo lectura" in h.descripcion


async def test_tool_inexistente():
    salida = await ejecutar("borrar_ordenes", {}, recursos())
    assert salida.codigo == "HERRAMIENTA_INEXISTENTE" and "consultar_equipos" in salida.mensaje


async def test_timeout_total_de_la_tool():
    class PlantaColgada(ClientePlanta):
        async def definicion(self):
            await asyncio.sleep(10)

    salida = await ejecutar("consultar_equipos", {}, Recursos(planta=PlantaColgada("http://x"),
                                                              materiales=recursos().materiales), timeout_s=0.05)
    assert salida.codigo == "TIMEOUT" and salida.reintentable


async def test_falla_inesperada_no_se_escapa():
    class PlantaRota(ClientePlanta):
        async def definicion(self):
            raise ZeroDivisionError

    salida = await ejecutar("consultar_equipos", {}, Recursos(planta=PlantaRota("http://x")))
    assert salida.codigo == "ERROR_INTERNO" and not salida.reintentable


async def test_structured_tools_de_langchain(api):
    tools = {t.name: t for t in herramientas_langchain(recursos())}
    assert list(tools) == NOMBRES
    assert tools["consultar_tareas"].args_schema is HERRAMIENTAS["consultar_tareas"].entrada

    ok = await tools["consultar_equipos"].ainvoke({"type": "tool_call", "id": "1", "name": "consultar_equipos",
                                                   "args": {"tag": "la dos"}})
    assert isinstance(ok, ToolMessage) and ok.status == "success"
    assert json.loads(ok.content)["equipos"][0]["tag"] == "B-102"


@pytest.mark.parametrize("args, codigo", [
    ({"tag": "B-104"}, "EQUIPO_INEXISTENTE"),
    ({"tag": "B-102", "inventado": 1}, "ARGUMENTOS_INVALIDOS"),
])
async def test_errores_en_langchain_vuelven_como_tool_message(api, args, codigo):
    (tool,) = [t for t in herramientas_langchain(recursos()) if t.name == "consultar_equipos"]
    msg = await tool.ainvoke({"type": "tool_call", "id": "1", "name": tool.name, "args": args})
    assert msg.status == "error"
    assert json.loads(msg.content)["codigo"] == codigo


async def test_mcp_lista_las_tools_de_solo_lectura():
    async with Client(crear_servidor(recursos())) as cliente:
        tools = (await cliente.list_tools()).tools
    assert [t.name for t in tools] == NOMBRES
    for t in tools:
        assert t.annotations.read_only_hint is True and t.annotations.idempotent_hint is True
        assert t.annotations.destructive_hint is False
        assert t.input_schema["additionalProperties"] is False and t.output_schema is not None
        assert t.description == HERRAMIENTAS[t.name].descripcion


async def test_mcp_llama_tools(api):
    async with Client(crear_servidor(recursos())) as cliente:
        tareas = await cliente.call_tool("consultar_tareas", {"codigo": "T-B-EMP"})
        equipos = await cliente.call_tool("consultar_equipos", {"tipo": "filtro"})
    assert not tareas.is_error and tareas.structured_content["tareas"][0]["costo_total_usd"] == 420
    assert json.loads(tareas.content[0].text)["tareas"][0]["codigo"] == "T-B-EMP"
    assert [e["tag"] for e in equipos.structured_content["equipos"]] == ["F-201A", "F-201B"]


async def test_mcp_errores_de_ejecucion_con_is_error(api):
    async with Client(crear_servidor(recursos())) as cliente:
        sin_sensor = await cliente.call_tool("consultar_historial_sensor", {
            "tag": "B-102", "variable": "caudal", "desde": "2026-11-10T00:00:00-03:00"})
        extra = await cliente.call_tool("consultar_repuestos", {"codigo": "TX-EMP-KIT", "reservar": True})
    assert sin_sensor.is_error and sin_sensor.structured_content["codigo"] == "SENSOR_INEXISTENTE"
    assert extra.is_error and extra.structured_content == {
        "codigo": "ARGUMENTOS_INVALIDOS", "reintentable": False, "mensaje": extra.structured_content["mensaje"]}


async def test_mcp_tool_inexistente_es_error_de_protocolo():
    async with Client(crear_servidor(recursos())) as cliente:
        with pytest.raises(MCPError) as e:
            await cliente.call_tool("crear_orden", {})
    assert "consultar_tareas" in str(e.value)


def test_app_http_responde_salud_e_initialize():
    with TestClient(crear_app(recursos())) as http:
        assert http.get("/salud").json()["tools"] == NOMBRES
        r = http.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                      json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "test", "version": "0"}}})
    assert r.status_code == 200 and "planta-pia3-consultas" in r.text
