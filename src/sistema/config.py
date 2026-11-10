from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(nombre: str, defecto: str) -> str:
    return os.environ.get(nombre, defecto)


@dataclass(frozen=True)
class Config:
    sistema: str = field(default_factory=lambda: _env("SISTEMA_NOMBRE", "Efrain Leon"))
    mqtt_host: str = field(default_factory=lambda: _env("MQTT_HOST", "broker"))
    mqtt_port: int = field(default_factory=lambda: int(_env("MQTT_PORT", "1883")))
    planta_url: str = field(default_factory=lambda: _env("PLANTA_URL", "http://sim:8100"))
    nube_url: str = field(default_factory=lambda: _env("NUBE_URL", "http://nube:8000"))
    proxy: str | None = field(default_factory=lambda: os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY"))
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql://sistema:sistema@db:5432/sistema"))
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://ollama:11434"))
    llm_modelo: str = field(default_factory=lambda: _env("LLM_MODELO", "qwen3.5:2b"))
    llm_hilos: int = field(default_factory=lambda: int(_env("LLM_HILOS", "2")))
    llm_timeout_s: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT_S", "45")))
    stt_modelo: str = field(default_factory=lambda: _env("STT_MODELO", "whisper:small"))
    stt_hilos: int = field(default_factory=lambda: int(_env("STT_HILOS", "2")))
    latido_s: float = field(default_factory=lambda: float(_env("LATIDO_S", "30")))
    sondeo_enlace_s: float = field(default_factory=lambda: float(_env("SONDEO_ENLACE_S", "10")))
    timeout_nota_s: float = field(default_factory=lambda: float(_env("TIMEOUT_NOTA_S", "180")))
    max_intentos_borrador: int = field(default_factory=lambda: int(_env("MAX_INTENTOS_BORRADOR", "3")))
    max_pasos_llm_por_nota: int = field(default_factory=lambda: int(_env("MAX_PASOS_LLM_POR_NOTA", "4")))
    max_tokens_por_nota: int = field(default_factory=lambda: int(_env("MAX_TOKENS_POR_NOTA", "12000")))


CONFIG = Config()
