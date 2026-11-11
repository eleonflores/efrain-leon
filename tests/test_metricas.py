from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from sistema.metricas import consumo_tokens

WHISPER, QWEN = "faster-whisper small int8", "qwen3.5:2b"
AHORA = datetime(2026, 11, 10, 21, 0, tzinfo=timezone.utc)


class ConsumoModelo(BaseModel):
    """Copia de `planta_sim/metricas.py` (la planta valida `sistema/metricas` con esto; no está en el contrato)."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    modelo: str = Field(min_length=1)
    tokens_entrada: int = Field(ge=0)
    tokens_salida: int = Field(ge=0)
    tokens_total: int = Field(ge=0)
    tokens_por_segundo: float | None = Field(default=None, ge=0)
    velocidad_estimada: bool = False

    @model_validator(mode="after")
    def comprobar_total(self):
        if self.tokens_total != self.tokens_entrada + self.tokens_salida:
            raise ValueError("El total debe ser entrada + salida")
        return self


class ConsumoTokens(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    ts: datetime
    sistema: str
    tokens_entrada: int = Field(ge=0)
    tokens_salida: int = Field(ge=0)
    tokens_total: int = Field(ge=0)
    tokens_por_segundo: float | None = Field(default=None, ge=0)
    velocidad_estimada: bool = False
    modelos: list[ConsumoModelo]

    @model_validator(mode="after")
    def comprobar_totales(self):
        for campo in ("tokens_entrada", "tokens_salida", "tokens_total"):
            if getattr(self, campo) != sum(getattr(m, campo) for m in self.modelos):
                raise ValueError("El total debe coincidir con el desglose por modelo")
        if len({m.modelo for m in self.modelos}) != len(self.modelos):
            raise ValueError("Cada modelo debe aparecer una sola vez")
        if self.ts.utcoffset() is None:
            raise ValueError("La fecha debe incluir la zona horaria")
        return self


def fila(modelo, entrada=0, salida=0, generacion_ms=0, estimado_ms=0):
    return {"modelo": modelo, "entrada": entrada, "salida": salida, "generacion_ms": generacion_ms,
            "estimado_ms": estimado_ms}


@pytest.mark.parametrize("filas", [
    [],
    [fila(WHISPER, salida=240, generacion_ms=30000), fila(QWEN)],
    [fila(QWEN, entrada=430, salida=50, estimado_ms=60000)],
    [fila("qwen3:1.7b", entrada=400, salida=40, generacion_ms=10000), fila(WHISPER, salida=30, generacion_ms=4000)],
], ids=["arranque", "timeout del llm", "filas sin tiempo de generacion", "modelo que ya no esta cargado"])
def test_el_consumo_valida_en_la_planta(filas):
    consumo = ConsumoTokens.model_validate(consumo_tokens(filas, [WHISPER, QWEN], "Efrain Leon", AHORA))
    assert [m.modelo for m in consumo.modelos][:2] == [WHISPER, QWEN]


def test_la_velocidad_es_salida_sobre_tiempo_de_generacion_ponderada_entre_modelos():
    filas = [fila(WHISPER, salida=240, generacion_ms=30000), fila(QWEN, entrada=430, salida=50, generacion_ms=12500)]
    consumo = consumo_tokens(filas, [WHISPER, QWEN], "Efrain Leon", AHORA)
    whisper, qwen = consumo["modelos"]
    assert (whisper["tokens_por_segundo"], qwen["tokens_por_segundo"]) == (8.0, 4.0)
    assert consumo["tokens_por_segundo"] == round(290 / 42.5, 2)
    assert not consumo["velocidad_estimada"]
