from pathlib import Path

import pytest
import yaml

from sistema.dominio.planta import Planta

DATOS = Path(__file__).parent / "datos"


@pytest.fixture(scope="session")
def planta() -> Planta:
    return Planta.desde_definicion(yaml.safe_load((DATOS / "planta.yaml").read_text(encoding="utf-8")))
