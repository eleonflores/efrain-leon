"""Servidor MCP con las tools de consulta de la planta (Streamable HTTP).

    python -m sistema.herramientas.servidor_mcp      # escucha en 0.0.0.0:$MCP_PUERTO (8001), endpoint /mcp
"""

from __future__ import annotations

import logging
import os

import mcp_types as types
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from sistema.herramientas.consultas import Recursos
from sistema.herramientas.modelos import ErrorHerramienta
from sistema.herramientas.registro import HERRAMIENTAS, a_json, ejecutar

log = logging.getLogger(__name__)

NOMBRE = "planta-pia3-consultas"
INSTRUCCIONES = ("Consultas de solo lectura sobre la planta de inyección PIA-3: equipos, historial de sensores, "
                 "historial de órdenes, inventario, catálogo de tareas y búsqueda en manuales (con citas). "
                 "Ninguna tool modifica nada.")


def _definiciones() -> list[types.Tool]:
    return [types.Tool(name=h.nombre, title=h.titulo, description=h.descripcion,
                       input_schema=h.entrada.model_json_schema(), output_schema=h.salida.model_json_schema(),
                       annotations=types.ToolAnnotations(title=h.titulo, read_only_hint=True, destructive_hint=False,
                                                         idempotent_hint=True, open_world_hint=False))
            for h in HERRAMIENTAS.values()]


def crear_servidor(recursos: Recursos | None = None) -> Server:
    recursos = recursos or Recursos()
    definiciones = _definiciones()
    esquemas = {d.name: d.input_schema for d in definiciones}

    async def listar(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=definiciones)

    async def llamar(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        if params.name not in HERRAMIENTAS:
            raise MCPError(types.INVALID_PARAMS,
                           f"No existe la tool '{params.name}'. Tools: {', '.join(HERRAMIENTAS)}.")
        resultado = await ejecutar(params.name, params.arguments or {}, recursos)
        return types.CallToolResult(content=[types.TextContent(text=a_json(resultado))],
                                    structured_content=resultado.model_dump(mode="json"),
                                    is_error=isinstance(resultado, ErrorHerramienta))

    return Server(NOMBRE, version="0.1.0", instructions=INSTRUCCIONES, get_tool_input_schema=esquemas.get,
                  on_list_tools=listar, on_call_tool=llamar)


async def _salud(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "tools": list(HERRAMIENTAS)})


def crear_app(recursos: Recursos | None = None, host: str = "0.0.0.0"):
    """App ASGI (Starlette) con el endpoint MCP en `/mcp` y `/salud` para el healthcheck."""
    return crear_servidor(recursos).streamable_http_app(streamable_http_path="/mcp", stateless_http=True, host=host,
                                                        custom_starlette_routes=[Route("/salud", _salud)])


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    puerto = int(os.environ.get("MCP_PUERTO", "8001"))
    log.info("Servidor MCP %s en http://%s:%d/mcp", NOMBRE, host, puerto)
    uvicorn.run(crear_app(host=host), host=host, port=puerto)


if __name__ == "__main__":
    main()
