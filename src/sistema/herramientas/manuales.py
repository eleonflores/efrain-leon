"""La sexta consulta de solo lectura: búsqueda en los manuales y el historial de PIA-3 (RAG).

Envuelve `sistema.rag.BuscadorManuales` con el mismo contrato que las otras cinco: recibe la entrada ya validada por
Pydantic, hace la validación semántica (el equipo existe) y lanza `FalloConsulta` cuando algo no cierra, para que el
registro lo convierta en un `ErrorHerramienta`.

Qué va por acá y qué no (ver `docs/rag.md`): manuales, catálogo de fallas, procedimientos, contrato y el texto libre
de las órdenes sí; límites de alarma, valores medidos y stock no. Esos tienen una fuente de verdad estructurada
(`/api/planta`, el historiador, materiales) y un número que sale del RAG puede ser el de un documento viejo. La tool
lo recuerda en `observacion` cuando la pregunta suena a límite o a stock.

El filtro de vigencia y de aplicabilidad lo pone el sistema, nunca el modelo: no hay argumento para pedir la Rev. C.
"""

from __future__ import annotations

import re
from typing import Protocol

from sistema.herramientas.consultas import FalloConsulta, Recursos
from sistema.herramientas.modelos import EntradaManuales, FragmentoManual, SalidaManuales
from sistema.rag.busqueda import ErrorRag, Filtros, Fragmento
from sistema.rag.consulta import ALIAS_EQUIPOS, equipos_en

_LIMITES = re.compile(r"\b(l[ií]mites?|alarmas?|disparos?|dispara|set ?points?)\b", re.IGNORECASE)
_STOCK = re.compile(r"\b(stock|almac[eé]n|inventario|existencias?|cu[aá]nt[oa]s .* hay)\b", re.IGNORECASE)

AVISO_LIMITES = ("Los valores de alarma y disparo vigentes salen de consultar_equipos (hoja de datos de la planta): "
                 "usá el manual para explicar el límite, no como fuente del número.")
AVISO_STOCK = ("El stock real sale de consultar_repuestos; el manual (MBP-4 §14.2) solo trae el stock de "
               "referencia.")
SIN_RESULTADOS = ("No hay fragmentos con esos filtros. Probá sin 'documento' o 'equipo', o con otras palabras "
                  "(síntomas, códigos).")


class Buscador(Protocol):
    """Lo que la tool necesita del RAG (en los tests, un doble sin Postgres ni modelo)."""

    @property
    def modo(self) -> str: ...

    async def buscar(self, pregunta: str, k: int = 5, filtros: Filtros | None = None) -> list[Fragmento]: ...


def resolver_equipo(dicho: str) -> str:
    """TAG exacto o nombre de campo ('la dos', 'el filtro B') → TAG. Los nombres son los del MBP-4 §2.2."""
    clave = re.sub(r"[\s_-]", "", dicho.upper())
    tag = next((t for t in ALIAS_EQUIPOS if t.replace("-", "") == clave), None)
    if tag is None:
        hallados = equipos_en(dicho)
        tag = hallados[0] if len(hallados) == 1 else None
    if tag is None:
        raise FalloConsulta("EQUIPO_INEXISTENTE", f"No existe el equipo '{dicho}' (o el nombre es ambiguo). Usá un "
                                                  f"TAG exacto: {', '.join(ALIAS_EQUIPOS)}.")
    return tag


def observacion(pregunta: str, hay_resultados: bool) -> str | None:
    avisos = [AVISO_LIMITES] if _LIMITES.search(pregunta) else []
    avisos += [AVISO_STOCK] if _STOCK.search(pregunta) else []
    avisos += [] if hay_resultados else [SIN_RESULTADOS]
    return " ".join(avisos) or None


async def buscar_en_manuales(e: EntradaManuales, r: Recursos) -> SalidaManuales:
    filtros = Filtros(documentos=(e.documento,) if e.documento else (),
                      equipo=resolver_equipo(e.equipo) if e.equipo else None)
    try:
        fragmentos = await r.manuales.buscar(e.pregunta, e.k, filtros)
    except ErrorRag as ex:
        raise FalloConsulta("RAG_NO_DISPONIBLE", f"{ex}. Seguí sin los manuales y avisá que no se consultaron.",
                            reintentable=True) from ex
    salida = [FragmentoManual(cita=f.cita, documento=f.documento, revision=f.revision, seccion=f.seccion,
                              titulo=f.titulo, pagina=f.pagina, fabricante=f.fabricante, texto=f.texto,
                              puntaje=f.puntaje) for f in fragmentos]
    return SalidaManuales(pregunta=e.pregunta, modo=r.manuales.modo, citas=[f.cita for f in salida],
                          fragmentos=salida, observacion=observacion(e.pregunta, bool(salida)))
