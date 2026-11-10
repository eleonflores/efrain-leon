import asyncio
import contextlib
from types import SimpleNamespace

import aiomqtt

from sistema.integraciones.mqtt import Bus


class ClienteFalso:
    def __init__(self, *args, **kwargs):
        self.messages = self._mensajes()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def subscribe(self, *args, **kwargs):
        pass

    async def publish(self, *args, **kwargs):
        pass

    async def _mensajes(self):
        yield SimpleNamespace(topic="planta/recorridas", payload=b'{"id": "NOTA-ROTA"}')
        yield SimpleNamespace(topic="planta/recorridas", payload=b'{"id": "NOTA-2"}')
        await asyncio.Event().wait()


async def test_un_mensaje_que_rompe_el_manejador_no_corta_la_recepcion(monkeypatch):
    monkeypatch.setattr(aiomqtt, "Client", ClienteFalso)
    recibidos = []

    async def manejador(topico, datos):
        if datos["id"] == "NOTA-ROTA":
            raise ValueError("no valida contra NotaRecorrida")
        recibidos.append(datos["id"])

    tarea = asyncio.create_task(Bus("broker", 1883, "test").correr(manejador, ["planta/#"]))
    for _ in range(100):
        if recibidos or tarea.done():
            break
        await asyncio.sleep(0.01)
    tarea.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarea

    assert recibidos == ["NOTA-2"]
