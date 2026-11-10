from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

import aiomqtt
from planta_contrato import EstadoSistema, EventoSistema, MensajeTablet, OrdenSistema, Topicos
from pydantic import BaseModel

log = logging.getLogger(__name__)

MODELO_POR_TOPICO: dict[str, type[BaseModel]] = {
    Topicos.EVENTOS: EventoSistema,
    Topicos.ORDENES: OrdenSistema,
    Topicos.ESTADO: EstadoSistema,
    Topicos.TABLET: MensajeTablet,
}

Manejador = Callable[[str, dict], Awaitable[None]]


def _json(modelo: BaseModel) -> str:
    def defecto(o):
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError(type(o))
    return json.dumps(modelo.model_dump(mode="json", exclude_none=False), ensure_ascii=False, default=defecto)


class Bus:
    def __init__(self, host: str, port: int, identificador: str):
        self.host, self.port, self.identificador = host, port, identificador
        self._cliente: aiomqtt.Client | None = None
        self._salida: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self.conectado = asyncio.Event()

    def publicar(self, topico: str, mensaje: BaseModel | dict) -> None:
        """Valida contra el contrato y encola. No bloquea."""
        modelo = MODELO_POR_TOPICO.get(topico)
        if modelo is not None:
            mensaje = modelo.model_validate(mensaje if isinstance(mensaje, dict) else mensaje.model_dump())
        payload = _json(mensaje) if isinstance(mensaje, BaseModel) else json.dumps(mensaje, ensure_ascii=False)
        self._salida.put_nowait((topico, payload))

    async def correr(self, manejador: Manejador, suscripciones: list[str]) -> None:
        while True:
            try:
                async with aiomqtt.Client(self.host, self.port, identifier=self.identificador,
                                          keepalive=30) as cliente:
                    self._cliente = cliente
                    for s in suscripciones:
                        await cliente.subscribe(s, qos=1)
                    self.conectado.set()
                    log.info("MQTT conectado a %s:%s", self.host, self.port)
                    envio = asyncio.create_task(self._enviar(cliente))
                    try:
                        async for m in cliente.messages:
                            try:
                                datos = json.loads(m.payload)
                            except (json.JSONDecodeError, UnicodeDecodeError):
                                log.warning("Mensaje no JSON en %s", m.topic)
                                continue
                            try:
                                await manejador(str(m.topic), datos)
                            except Exception:  # noqa: BLE001
                                log.exception("Mensaje descartado en %s", m.topic)
                    finally:
                        envio.cancel()
            except aiomqtt.MqttError as e:
                self.conectado.clear()
                self._cliente = None
                log.warning("MQTT desconectado (%s); reintento en 2 s", e)
                await asyncio.sleep(2)

    async def _enviar(self, cliente: aiomqtt.Client) -> None:
        while True:
            topico, payload = await self._salida.get()
            try:
                await cliente.publish(topico, payload, qos=1)
            except aiomqtt.MqttError:
                self._salida.put_nowait((topico, payload))
                raise
