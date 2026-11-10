"""Respuestas reales de la API de la planta (`datos/api_*.json`) servidas con respx, sin red."""

import json
from pathlib import Path

import respx

from sistema.herramientas import Recursos
from sistema.herramientas.materiales import MaterialesYaml
from sistema.integraciones.planta_api import ClientePlanta

DATOS = Path(__file__).parent / "datos"
URL = "http://planta.test"


def dato(nombre: str):
    return json.loads((DATOS / nombre).read_text(encoding="utf-8"))


def recursos() -> Recursos:
    return Recursos(planta=ClientePlanta(URL, timeout_s=0.5, backoff_s=0),
                    materiales=MaterialesYaml(DATOS / "materiales.yaml"))


def simular_planta() -> respx.MockRouter:
    m = respx.mock(base_url=URL, assert_all_called=False)
    m.get("/api/planta", name="planta").respond(json=dato("api_planta.json"))
    return m
