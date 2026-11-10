from __future__ import annotations

import asyncio
import functools
import logging
import ssl
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from sistema.config import CONFIG

log = logging.getLogger(__name__)

ZONA_PLANTA = timezone(timedelta(hours=-3))


@functools.cache
def _contexto_ssl() -> ssl.SSLContext:
    return ssl.create_default_context()


class ErrorPlanta(Exception):
    def __init__(self, codigo: str, mensaje: str, reintentable: bool):
        super().__init__(mensaje)
        self.codigo, self.mensaje, self.reintentable = codigo, mensaje, reintentable


def a_hora_planta(momento: datetime) -> datetime:
    """Una fecha sin offset se toma como hora de planta."""
    if momento.tzinfo is None:
        return momento.replace(tzinfo=ZONA_PLANTA)
    return momento.astimezone(ZONA_PLANTA)


def _iso_planta(momento: datetime | None) -> str | None:
    return None if momento is None else a_hora_planta(momento).isoformat(timespec="seconds")


def _sin_nulos(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


class ClientePlanta:
    def __init__(self, url: str | None = None, *, timeout_s: float = 5.0, reintentos: int = 2,
                 backoff_s: float = 0.5):
        self.url = (url or CONFIG.planta_url).rstrip("/")
        self.timeout_s, self.reintentos, self.backoff_s = timeout_s, reintentos, backoff_s
        self._definicion: dict | None = None

    async def definicion(self) -> dict:
        """`GET /api/planta`: equipos, sensores y límites."""
        if self._definicion is None:
            datos = await self._get("/api/planta")
            if not isinstance(datos, dict) or not isinstance(datos.get("equipos"), list):
                raise ErrorPlanta("RESPUESTA_INVALIDA", "La planta devolvió una definición sin equipos.", False)
            self._definicion = datos
        return self._definicion

    async def historian(self, tag: str, variable: str, desde: datetime | None = None,
                        hasta: datetime | None = None) -> list[dict]:
        """`GET /api/historian/{tag}/{variable}`: `[{ts, valor}]`, una muestra por minuto (valor puede ser null)."""
        datos = await self._get(f"/api/historian/{tag}/{variable}",
                                _sin_nulos({"desde": _iso_planta(desde), "hasta": _iso_planta(hasta)}))
        return self._lista(datos, "historiador")

    async def historial_ordenes(self, equipo: str | None = None, desde: datetime | None = None,
                                hasta: datetime | None = None) -> list[dict]:
        """`GET /api/historial-ordenes`: órdenes del archivo (texto libre de campo) y las del simulador."""
        datos = await self._get("/api/historial-ordenes", _sin_nulos(
            {"equipo": equipo, "desde": _iso_planta(desde), "hasta": _iso_planta(hasta)}))
        return self._lista(datos, "historial de órdenes")

    @staticmethod
    def _lista(datos: Any, que: str) -> list[dict]:
        if not isinstance(datos, list):
            raise ErrorPlanta("RESPUESTA_INVALIDA", f"El {que} de la planta no devolvió una lista.", False)
        return datos

    async def _get(self, ruta: str, params: dict[str, Any] | None = None) -> Any:
        intentos = self.reintentos + 1
        ultimo: ErrorPlanta | None = None
        for intento in range(intentos):
            if intento:
                await asyncio.sleep(self.backoff_s * 2 ** (intento - 1))
            try:
                async with httpx.AsyncClient(base_url=self.url, timeout=self.timeout_s, trust_env=False,
                                             verify=_contexto_ssl()) as http:
                    r = await http.get(ruta, params=params)
            except httpx.TimeoutException:
                ultimo = ErrorPlanta("PLANTA_TIMEOUT", f"La planta no respondió en {self.timeout_s:g} s", True)
            except httpx.TransportError as e:
                ultimo = ErrorPlanta("PLANTA_NO_DISPONIBLE",
                                     f"No hay conexión con la planta en {self.url} ({type(e).__name__})", True)
            else:
                if r.status_code >= 500:
                    ultimo = ErrorPlanta("PLANTA_NO_DISPONIBLE", f"La planta respondió HTTP {r.status_code}", True)
                elif r.status_code >= 400:
                    raise ErrorPlanta("PLANTA_RECHAZO",
                                      f"La planta rechazó la consulta {ruta} (HTTP {r.status_code}): {r.text[:300]}",
                                      False)
                else:
                    try:
                        return r.json()
                    except ValueError:
                        raise ErrorPlanta("RESPUESTA_INVALIDA", f"La planta respondió algo que no es JSON en {ruta}.",
                                          False) from None
            log.warning("GET %s falló (intento %d de %d): %s", ruta, intento + 1, intentos, ultimo.mensaje)
        assert ultimo is not None
        raise ErrorPlanta(ultimo.codigo, f"{ultimo.mensaje} después de {intentos} intentos. Probá de nuevo en unos "
                                         f"segundos; si sigue igual, seguí sin este dato y avisá que no se pudo "
                                         f"consultar.", True)
