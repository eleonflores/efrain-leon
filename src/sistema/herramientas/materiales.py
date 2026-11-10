"""Repuestos, stock, listas de materiales y catálogo de tareas."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import BaseModel, Field, ValidationError

RAIZ_REPO = Path(__file__).resolve().parents[3]
RUTAS_POR_DEFECTO = (RAIZ_REPO / "datos" / "materiales.yaml", Path("/app/datos/materiales.yaml"))


class ErrorMateriales(Exception):
    """No se pudo leer el catálogo de materiales (archivo ausente o con formato inválido)."""


class Stock(BaseModel):
    yacimiento: int = Field(ge=0)
    central: int = Field(ge=0)


class Repuesto(BaseModel):
    codigo: str
    nombre: str
    unidad: str
    costo_usd: float = Field(ge=0)
    stock: Stock


class RepuestoDeTarea(BaseModel):
    codigo: str
    cantidad: float = Field(gt=0)


class Tarea(BaseModel):
    codigo: str
    nombre: str
    estandar: bool
    equipos: list[str] = []
    detiene: bool
    horas: float = Field(ge=0)
    ejecutor: Literal["propio", "contratista"]
    # None: el catálogo no dice qué repuestos lleva; []: no lleva ninguno.
    repuestos: list[RepuestoDeTarea] | None = None


class CatalogoMateriales(BaseModel):
    repuestos: dict[str, Repuesto]
    lista_materiales: dict[str, list[str]]
    tareas: list[Tarea]

    @classmethod
    def desde_dict(cls, d: dict) -> "CatalogoMateriales":
        tareas = [Tarea(estandar=True, **t) for t in d.get("tareas_estandar") or []]
        tareas += [Tarea(estandar=False, **t) for t in d.get("tareas_no_estandar") or []]
        return cls(repuestos={r["codigo"]: Repuesto(**r) for r in d.get("repuestos") or []},
                   lista_materiales=d.get("lista_materiales") or {}, tareas=tareas)


class RepositorioMateriales(Protocol):
    async def cargar(self) -> CatalogoMateriales: ...


def ruta_materiales() -> Path:
    """`MATERIALES_PATH` si está definida; si no, `datos/materiales.yaml` del repo o `/app/datos/` en la imagen."""
    if os.environ.get("MATERIALES_PATH"):
        return Path(os.environ["MATERIALES_PATH"])
    return next((r for r in RUTAS_POR_DEFECTO if r.exists()), RUTAS_POR_DEFECTO[0])


class MaterialesYaml:
    def __init__(self, ruta: Path | str | None = None):
        self.ruta = Path(ruta) if ruta else ruta_materiales()
        self._catalogo: CatalogoMateriales | None = None

    async def cargar(self) -> CatalogoMateriales:
        if self._catalogo is None:
            self._catalogo = await asyncio.to_thread(self._leer)
        return self._catalogo

    def _leer(self) -> CatalogoMateriales:
        try:
            datos = yaml.safe_load(self.ruta.read_text(encoding="utf-8"))
            return CatalogoMateriales.desde_dict(datos or {})
        except FileNotFoundError:
            raise ErrorMateriales(f"Falta el catálogo de materiales en {self.ruta}: revisá MATERIALES_PATH.") from None
        except (yaml.YAMLError, ValidationError, TypeError, KeyError) as e:
            raise ErrorMateriales(f"El catálogo de materiales {self.ruta} tiene un formato inválido: {e}") from None
