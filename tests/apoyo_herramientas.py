"""Apoyo para los tests de las tools de consulta.

Los JSON de `tests/datos/api_*.json` son respuestas reales copiadas de la planta corriendo (escenario `libre`). Los
tests no tocan la red: la API se simula con respx sobre una URL que no existe.
"""

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
    """Cliente rápido para los tests: timeout corto y reintentos sin espera."""
    return Recursos(planta=ClientePlanta(URL, timeout_s=0.5, backoff_s=0),
                    materiales=MaterialesYaml(DATOS / "materiales.yaml"))


def simular_planta() -> respx.MockRouter:
    """Router de respx con `GET /api/planta` ya cargado. Usar como context manager."""
    m = respx.mock(base_url=URL, assert_all_called=False)
    m.get("/api/planta", name="planta").respond(json=dato("api_planta.json"))
    return m
