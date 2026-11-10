"""Catálogo de la planta: equipos, nombres informales, unidades de los manómetros y límites de alarma."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sistema.procesamiento.numeros import sin_tildes

# Conversión a kg/cm² (1 kg/cm² = 14,2233 psi = 0,980665 bar).
A_KG = {"kg/cm2": 1.0, "psi": 1 / 14.2233, "bar": 1 / 0.980665}
# lectura local del operador → sensor conectado con el que se compara
SENSOR_DE_LECTURA = {"presion_descarga_local": "presion_descarga", "presion_diferencial": "presion_diferencial",
                     "presion_diferencial_local": "presion_diferencial"}
UNIDAD_POR_VARIABLE = {"presion_diferencial": "kg/cm2", "presion_diferencial_local": "kg/cm2", "nivel": "m",
                       "temperatura_rodamiento_ir": "degC", "temperatura_motor_ir": "degC",
                       "goteo_empaquetadura": "gotas/min"}


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", sin_tildes(texto.lower())).strip()


@dataclass
class Equipo:
    tag: str
    tipo: str
    nombres: list[str]
    unidad_manometro: str | None = None
    rol_inicial: str | None = None


@dataclass
class Planta:
    equipos: dict[str, Equipo]
    limites: dict[tuple[str, str], dict] = field(default_factory=dict)

    @classmethod
    def desde_definicion(cls, d: dict) -> "Planta":
        equipos = {}
        for e in d["equipos"]:
            equipos[e["tag"]] = Equipo(e["tag"], e["tipo"], list(e.get("nombres", [])),
                                       (e.get("manometro_local") or {}).get("unidad"), e.get("rol_inicial"))
        limites = {(s["tag"], s["variable"]): s for s in d.get("sensores", [])}
        return cls(equipos, limites)

    def bombas(self) -> list[Equipo]:
        return [e for e in self.equipos.values() if e.tipo == "bomba"]

    def resolver(self, dicho: str | None) -> str | None:
        """'la dos' → 'B-102'. Devuelve None si no se puede saber de qué equipo habla ("la bomba" a secas)."""
        if not dicho:
            return None
        d = _norm(dicho)
        if d.upper().replace(" ", "") in {t.replace("-", "") for t in self.equipos} or dicho.upper() in self.equipos:
            return next(t for t in self.equipos if t.replace("-", "") == d.upper().replace(" ", "").replace("-", ""))
        candidatos = []
        for e in self.equipos.values():
            for n in e.nombres + [e.tag.lower()]:
                nn = _norm(n)
                if d == nn or re.search(rf"\b{re.escape(nn)}\b", d):
                    candidatos.append((len(nn), e.tag))
        if not candidatos:
            return None
        candidatos.sort(reverse=True)
        mejores = {t for largo, t in candidatos if largo == candidatos[0][0]}
        return mejores.pop() if len(mejores) == 1 else None

    def equipos_en_texto(self, texto: str) -> list[str]:
        """Todos los equipos nombrados en un texto, en orden de aparición."""
        t = _norm(texto)
        hallados: list[tuple[int, int, str]] = []
        for e in self.equipos.values():
            for n in e.nombres:
                for m in re.finditer(rf"\b{re.escape(_norm(n))}\b", t):
                    hallados.append((m.start(), -len(n), e.tag))
        hallados.sort()
        salida, ocupado_hasta = [], -1
        for inicio, menos_largo, tag in hallados:
            if inicio > ocupado_hasta:
                salida.append(tag)
                ocupado_hasta = inicio - menos_largo
        return salida

    def unidad_por_defecto(self, tag: str, variable: str) -> str | None:
        if variable == "presion_descarga_local":
            return self.equipos[tag].unidad_manometro if tag in self.equipos else None
        return UNIDAD_POR_VARIABLE.get(variable)

    def fuera_de_alarma(self, tag: str, variable: str, valor: float | None, unidad: str | None) -> str | None:
        """Si la lectura está fuera de los límites de alarma de la hoja de datos, dice cuál. Si no, None."""
        sensor = SENSOR_DE_LECTURA.get(variable, variable)
        lim = self.limites.get((tag, sensor))
        if lim is None or valor is None:
            return None
        v = valor * A_KG.get(unidad or "kg/cm2", 1.0) if unidad in A_KG or sensor.startswith("presion") else valor
        if lim.get("alarma_alta") is not None and v >= lim["alarma_alta"]:
            return f"{sensor} {v:.2f} ≥ alarma alta {lim['alarma_alta']}"
        if lim.get("alarma_baja") is not None and v <= lim["alarma_baja"]:
            return f"{sensor} {v:.2f} ≤ alarma baja {lim['alarma_baja']}"
        return None
