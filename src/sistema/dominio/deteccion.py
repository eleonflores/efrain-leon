"""Detección en planta: de un parte confirmado o de los sensores a `SinNovedad` / `Escalado`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sistema.dominio.planta import Planta
from sistema.procesamiento.numeros import sin_tildes

VARIABLES_ANOMALAS = {
    "goteo_empaquetadura": "pérdida por empaquetadura",
    "nivel_aceite_visor": "nivel de aceite bajo",
    "estado_correas": "correas en mal estado",
    "ruido": "ruido anormal",
}
# máximo normal de TX350-D §3.2 más 5 °C
UMBRAL_TEMPERATURA_IR = {"temperatura_rodamiento_ir": 75.0, "temperatura_motor_ir": 65.0}
# descarga por debajo de la cual la bomba está parada (marca ~1,6 kg/cm²)
BOMBA_PARADA_KG = 30.0


@dataclass
class Decision:
    tag: str | None
    tipo: str                    # "SinNovedad" | "Escalado"
    motivos: list[str] = field(default_factory=list)


def _anomalia(fila: dict, planta: Planta) -> str | None:
    variable, valor = fila["variable"], fila.get("valor")
    obs = sin_tildes((fila.get("observacion") or "").lower())
    if variable in VARIABLES_ANOMALAS:
        return VARIABLES_ANOMALAS[variable]
    if variable == "estado":
        if any(p in obs for p in ("dispar", "no arranca", "falla", "trabad")):
            return f"bomba {fila.get('observacion')}"
        return None                                  # "parada, en reserva", "parada por mantenimiento"
    if variable == "nivel" and "rebals" in obs:
        return "tanque rebalsando"
    if variable in UMBRAL_TEMPERATURA_IR and valor is not None and valor > UMBRAL_TEMPERATURA_IR[variable]:
        return f"{variable} {valor:g} °C > {UMBRAL_TEMPERATURA_IR[variable]:g} °C"
    if fila.get("tag"):
        return planta.fuera_de_alarma(fila["tag"], variable, valor, fila.get("unidad"))
    return None


def evaluar_parte(filas: list[dict], planta: Planta) -> list[Decision]:
    """Una decisión por equipo del parte, en el orden en que aparecen. Parte vacío → un SinNovedad general."""
    decisiones: dict[str | None, Decision] = {}
    for f in filas:
        d = decisiones.setdefault(f.get("tag"), Decision(f.get("tag"), "SinNovedad"))
        motivo = _anomalia(f, planta)
        if motivo:
            d.tipo = "Escalado"
            d.motivos.append(motivo)
    return list(decisiones.values()) or [Decision(None, "SinNovedad")]


@dataclass
class _Seguimiento:
    desde: datetime | None = None
    escalado: bool = False


class MonitorSensores:
    """Escala los desvíos de sensores que duran `persistencia`, medida en el `ts` de las lecturas."""

    def __init__(self, planta: Planta, persistencia: timedelta = timedelta(minutes=30)):
        self.planta, self.persistencia = planta, persistencia
        self._estado: dict[tuple[str, str], _Seguimiento] = {}

    def lectura(self, tag: str, variable: str, valor: float | None, ts: datetime) -> Decision | None:
        """Devuelve una decisión Escalado la primera vez que un desvío cumple la persistencia; si no, None."""
        s = self._estado.setdefault((tag, variable), _Seguimiento())
        parada = variable == "presion_descarga" and valor is not None and valor < BOMBA_PARADA_KG
        fuera = valor is not None and not parada and self.planta.fuera_de_alarma(tag, variable, valor, None)
        if not fuera:
            s.desde, s.escalado = None, False        # sin dato (bomba parada) o en rango: se reinicia
            return None
        if s.desde is None:
            s.desde = ts
        if not s.escalado and ts - s.desde >= self.persistencia:
            s.escalado = True
            return Decision(tag, "Escalado", [f"{fuera} sostenido desde {s.desde:%d/%m %H:%M}"])
        return None

    def inicio_del_desvio(self, tag: str, variable: str) -> datetime | None:
        s = self._estado.get((tag, variable))
        return s.desde if s else None
