from pathlib import Path

import pytest
import yaml

from sistema.dominio.planta import Planta

DATOS = Path(__file__).parent / "datos"


@pytest.fixture(scope="session")
def definicion_planta() -> dict:
    """La misma definición que devuelve `GET /api/planta` (copia de `datos/planta.yaml` de la planta)."""
    return yaml.safe_load((DATOS / "planta.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def materiales() -> dict:
    return yaml.safe_load((DATOS / "materiales.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def planta(definicion_planta) -> Planta:
    return Planta.desde_definicion(definicion_planta)
