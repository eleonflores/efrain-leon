from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TypeVar

import httpx
from langchain_ollama import ChatOllama
from pydantic import BaseModel

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class PresupuestoAgotado(Exception):
    pass


@dataclass
class Paso:
    etapa: str
    modelo: str
    tokens_entrada: int
    tokens_salida: int
    duracion_ms: int
    ok: bool
    costo_usd: float = 0.0
    detalle: dict = field(default_factory=dict)


@dataclass
class Presupuesto:
    max_pasos: int
    max_tokens: int
    pasos: int = 0
    tokens: int = 0

    def controlar(self) -> None:
        if self.pasos >= self.max_pasos or self.tokens >= self.max_tokens:
            raise PresupuestoAgotado(f"{self.pasos} pasos, {self.tokens} tokens")


class ModeloLocal:
    def __init__(self, url: str, modelo: str, num_ctx: int = 4096, num_predict: int = 700, hilos: int | None = None,
                 timeout_s: float = 90):
        self.nombre, self.url = modelo, url.rstrip("/")
        self.timeout_s = timeout_s
        self.chat = ChatOllama(model=modelo, base_url=url, temperature=0, reasoning=False, num_ctx=num_ctx,
                               num_predict=num_predict, num_thread=hilos, keep_alive="24h")
        self._turno = asyncio.Semaphore(1)

    async def cargar(self) -> float:
        """Carga el modelo en memoria sin generar; devuelve los segundos que tardó."""
        t0 = time.perf_counter()
        async with httpx.AsyncClient(trust_env=False, timeout=180) as http:
            r = await http.post(f"{self.url}/api/generate", json={"model": self.nombre, "keep_alive": "24h"})
            r.raise_for_status()
        return time.perf_counter() - t0

    async def estructurado(self, instrucciones: str, entrada: str, esquema: type[T], etapa: str,
                           presupuesto: Presupuesto | None = None) -> tuple[T | None, Paso]:
        """Pide una salida con el JSON Schema de `esquema` y la valida. Devuelve (resultado o None, paso)."""
        if presupuesto:
            presupuesto.controlar()
        runnable = self.chat.with_structured_output(esquema, method="json_schema", include_raw=True)
        t0 = time.perf_counter()
        resultado, crudo, error = None, None, None
        async with self._turno:
            try:
                salida = await asyncio.wait_for(runnable.ainvoke([("system", instrucciones), ("human", entrada)]),
                                                self.timeout_s)
                crudo, resultado, error = salida["raw"], salida["parsed"], salida.get("parsing_error")
            except Exception as e:  # noqa: BLE001
                error = e
        uso = (getattr(crudo, "usage_metadata", None) or {}) if crudo is not None else {}
        paso = Paso(etapa, self.nombre, int(uso.get("input_tokens", 0)), int(uso.get("output_tokens", 0)),
                    int((time.perf_counter() - t0) * 1000), resultado is not None,
                    detalle={"error": repr(error)} if error else {})
        if presupuesto:
            presupuesto.pasos += 1
            presupuesto.tokens += paso.tokens_entrada + paso.tokens_salida
        if error:
            log.warning("LLM %s falló en %s: %r", self.nombre, etapa, error)
        return resultado, paso
