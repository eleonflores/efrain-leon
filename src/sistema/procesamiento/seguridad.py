"""Detector de condiciones inseguras (S1 a S4) por reglas sobre la transcripción."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sistema.procesamiento.numeros import sin_tildes

PATRONES: dict[str, list[str]] = {
    "S1": [r"agua a presion", r"sale agua\b.*\b(presion|todos lados|fuerza)", r"chorro de agua",
           r"proyeccion de agua", r"se rompio\b.*\bdescarga", r"revento\b.*\b(descarga|cano|niple|manguera)",
           r"(salta|tira|larga) agua\b.*\b(presion|todos lados)"],
    "S2": [r"olor a gas", r"huele a gas", r"(perdida|fuga|escape) de gas", r"\bgas fuerte\b"],
    "S3": [r"\bhumo\b", r"\bfuego\b", r"olor a quemado", r"\bllamas?\b", r"\bincendio\b", r"se (esta )?prendi\w* fuego"],
    "S4": [r"\bse (golpeo|lastimo|corto|cayo|quemo|lesiono|machuco|accidento)\b", r"\bsangr(a|ando|e)\b",
           r"\b(lesionad|herid|accidentad)[oa]s?\b", r"\b(no se puede mover|esta inconsciente|se desmayo)\b"],
}
DESCRIPCION = {
    "S1": "pérdida con proyección de agua a presión",
    "S2": "olor a gas",
    "S3": "humo o fuego",
    "S4": "persona lesionada",
}
_COMPILADOS = {c: [re.compile(p) for p in ps] for c, ps in PATRONES.items()}


@dataclass(frozen=True)
class Condicion:
    codigo: str
    descripcion: str
    evidencia: str


def detectar(texto: str) -> list[Condicion]:
    t = re.sub(r"\s+", " ", sin_tildes((texto or "").lower()))
    hallazgos = []
    for codigo, patrones in _COMPILADOS.items():
        for p in patrones:
            m = p.search(t)
            if m:
                hallazgos.append(Condicion(codigo, DESCRIPCION[codigo], m.group(0)))
                break
    return hallazgos


def mensaje_emergencia(condiciones: list[Condicion], equipo: str | None) -> str:
    que = " y ".join(c.descripcion for c in condiciones)
    donde = f" en {equipo}" if equipo else ""
    return (f"ALERTA DE SEGURIDAD: {que}{donde}. Aplicá ya el procedimiento de emergencia: alejate de la zona, "
            f"no intentes intervenir solo y avisá por radio al supervisor de turno.")
