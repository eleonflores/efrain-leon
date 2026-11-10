"""Estado del enlace de la planta con la nube.

La única salida de la planta es el proxy `enlace:3128`; cuando el enlace se cae, el proxy cierra la conexión sin
responder. El estado se sondea pidiendo `/salud` al servicio de la nube a través del proxy.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

log = logging.getLogger(__name__)


class Enlace:
    def __init__(self, nube_url: str, proxy: str | None, intervalo_s: float):
        self.nube_url, self.proxy, self.intervalo_s = nube_url.rstrip("/"), proxy, intervalo_s
        self.ok = False
        self.cambio = asyncio.Event()

    async def sondear(self) -> bool:
        try:
            async with httpx.AsyncClient(proxy=self.proxy, timeout=5) as http:
                r = await http.get(f"{self.nube_url}/salud")
                return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def correr(self) -> None:
        while True:
            ok = await self.sondear()
            if ok != self.ok:
                log.info("Enlace %s", "ARRIBA" if ok else "CAÍDO")
                self.ok = ok
                self.cambio.set()
            await asyncio.sleep(self.intervalo_s)
