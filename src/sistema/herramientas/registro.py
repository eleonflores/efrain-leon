"""Registro de las tools de consulta: nombre, descripción para el modelo, contratos y cómo ejecutarlas.

`ejecutar()` es el único camino para correr una tool, lo use el agente (vía LangChain) o un cliente MCP. Aplica las
capas en orden: validación sintáctica (Pydantic, `extra="forbid"`) → validación semántica (dentro de cada consulta) →
ejecución con un timeout total. Nunca lanza: cualquier falla vuelve como `ErrorHerramienta` con `codigo`, `mensaje`
y `reintentable`, para que el loop siga y el modelo pueda corregir. Los reintentos ante fallas transitorias de la
planta ya los hace el cliente HTTP; acá no se reintenta de nuevo.

Para sumar una tool se agrega una `Herramienta` a `HERRAMIENTAS` (así se sumó `buscar_en_manuales`, el RAG).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, ValidationError

from sistema.herramientas.consultas import (
    FalloConsulta, Recursos, consultar_equipos, consultar_historial_ordenes, consultar_historial_sensor,
    consultar_repuestos, consultar_tareas,
)
from sistema.herramientas.manuales import buscar_en_manuales
from sistema.herramientas.materiales import ErrorMateriales
from sistema.herramientas.modelos import (
    EntradaEquipos, EntradaHistorialOrdenes, EntradaHistorialSensor, EntradaManuales, EntradaRepuestos, EntradaTareas,
    ErrorHerramienta, SalidaEquipos, SalidaHistorialOrdenes, SalidaHistorialSensor, SalidaManuales, SalidaRepuestos,
    SalidaTareas,
)
from sistema.integraciones.planta_api import ErrorPlanta

log = logging.getLogger(__name__)

# Cubre el peor caso del cliente HTTP (3 intentos de 5 s más el backoff) con margen.
TIMEOUT_TOOL_S = 20.0

GARANTIAS = ("\n\nSolo lectura e idempotente: no modifica nada. Si falla devuelve {codigo, mensaje, reintentable}: "
             "con reintentable=false corregí los argumentos según el mensaje; con true (planta caída o lenta) podés "
             "reintentar más tarde o seguir sin el dato.")


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    titulo: str
    descripcion: str
    entrada: type[BaseModel]
    salida: type[BaseModel]
    funcion: Callable[[Any, Recursos], Awaitable[BaseModel]]


_LISTA = [
    Herramienta(
        "consultar_equipos", "Equipos de la planta",
        "Catálogo de equipos de la planta PIA-3: TAG, tipo, descripción, fabricante y modelo, nombres informales que "
        "usan los operadores ('la dos', 'el filtro B'), unidad del manómetro local de cada bomba (kg/cm2, psi o bar), "
        "sensores conectados con sus límites de alarma de la hoja de datos y lecturas locales de la recorrida.\n"
        "Usala para pasar un nombre informal a TAG, saber en qué unidad lee el manómetro local de una bomba, conocer "
        "los límites de alarma o qué variables tienen historial.\n"
        "No la uses para valores medidos (consultar_historial_sensor) ni para repuestos (consultar_repuestos).\n"
        "Sin filtros devuelve los 7 equipos." + GARANTIAS,
        EntradaEquipos, SalidaEquipos, consultar_equipos),
    Herramienta(
        "consultar_historial_sensor", "Historial de un sensor",
        "Resumen del historial de UN sensor conectado de un equipo (historiador de la planta: una muestra por minuto, "
        "últimos 45 días del reloj de la planta). Devuelve cantidad de muestras, mínimo, máximo, promedio, "
        "percentiles 5 y 95, la última muestra con su hora, cuántas muestras quedaron fuera de los límites de alarma "
        "y una serie de a lo sumo max_puntos puntos (promedio por tramo) para ver la tendencia.\n"
        "Usala para ver cómo venía una variable (p. ej. presión de descarga de B-102 en las últimas 6 h), comparar "
        "una lectura de la recorrida con el sensor o confirmar una tendencia.\n"
        "No la uses para lecturas locales (manómetro local, temperatura infrarroja, goteo, visor de aceite, correas, "
        "nivel del tanque): no están en el historiador. Para saber qué sensores tiene cada equipo usá "
        "consultar_equipos.\n"
        "Un equipo y una variable por llamada; 'desde' es obligatorio; nunca devuelve las muestras crudas. Las fechas "
        "son del reloj de la planta (el de las notas), no la hora real." + GARANTIAS,
        EntradaHistorialSensor, SalidaHistorialSensor, consultar_historial_sensor),
    Herramienta(
        "consultar_historial_ordenes", "Historial de órdenes de trabajo",
        "Órdenes de trabajo históricas (archivo de 2 años con el texto libre de campo, más las recientes del "
        "simulador), de la más nueva a la más vieja: fecha, tipo, tareas, ejecutor, estado, aviso, trabajo "
        "realizado, repuestos usados, horas y código de falla.\n"
        "Usala para saber qué se le hizo antes a un equipo, cuándo se hizo por última vez una tarea (filtrá con "
        "'tarea') o si una falla se repite. Las órdenes generales, como la medición mensual de vibraciones de las "
        "tres bombas, están cargadas con equipo 'PLANTA'.\n"
        "Devuelve como mucho 'limite' órdenes (por defecto 10) y el total encontrado: si total > devueltas, acotá con "
        "desde/hasta o tarea. No crea ni modifica órdenes." + GARANTIAS,
        EntradaHistorialOrdenes, SalidaHistorialOrdenes, consultar_historial_ordenes),
    Herramienta(
        "consultar_repuestos", "Inventario y lista de materiales",
        "Inventario de repuestos: código, nombre, unidad, costo unitario en USD, stock en los dos almacenes "
        "('yacimiento' = el de la planta, disponible ya; 'central' = Comodoro Rivadavia, demora de 3 a 5 días) y a "
        "qué equipos corresponde cada uno.\n"
        "Con 'equipo' devuelve la lista de materiales de ese equipo; con 'codigo', ese repuesto; sin filtros, el "
        "inventario completo.\n"
        "Usala para verificar stock o estimar el costo de una tarea no estándar. Para los repuestos y el costo de una "
        "tarea del catálogo usá consultar_tareas. No reserva ni descuenta stock." + GARANTIAS,
        EntradaRepuestos, SalidaRepuestos, consultar_repuestos),
    Herramienta(
        "consultar_tareas", "Catálogo de tareas",
        "Catálogo de tareas de mantenimiento: estándar (plan de mantenimiento, con equipos y repuestos asignados) y "
        "no estándar (siempre requieren aprobación del planificador). Por tarea: código, nombre, si detiene el "
        "equipo, horas, ejecutor (propio o contratista), repuestos con cantidad, costo y stock, y costo total de "
        "repuestos en USD.\n"
        "Con 'equipo' devuelve sus tareas estándar más todas las no estándar (el catálogo no les asigna equipo). Con "
        "'codigo', esa tarea (T-F-CAR tiene una variante por filtro).\n"
        "Usala para elegir la tarea de una orden y conocer su impacto (detención, horas, costo, stock). "
        "costo_total_usd es null cuando el catálogo no lista los repuestos de la tarea (no estándar): estimalo con "
        "consultar_repuestos. El catálogo no incluye mano de obra." + GARANTIAS,
        EntradaTareas, SalidaTareas, consultar_tareas),
    Herramienta(
        "buscar_en_manuales", "Búsqueda en manuales e historial",
        "Busca en los documentos de PIA-3 y devuelve fragmentos con su cita ('TX350-D §3.2', 'historial "
        "OT-25-0026'): manual de la bomba Trimax TX-350 (Rev. D, la vigente), manual del filtro Filtrapat FC-48, "
        "manual de buenas prácticas de la operadora MBP-4 (catálogo de fallas F01-F10 y su correspondencia con los "
        "códigos del fabricante, diagnóstico por síntoma, reglas de aprobación, roles, seguridad), contrato con "
        "Servipat y cierres de ejemplo, y el texto libre de las órdenes de trabajo de los últimos dos años.\n"
        "Usala para diagnosticar por síntomas, buscar la causa probable o el procedimiento, traducir un código del "
        "fabricante (TX-T07) al catálogo de la planta (F09), ver qué se encontró antes en un equipo o qué dice el "
        "contrato. Cada conclusión que saques de acá tiene que llevar la cita del fragmento.\n"
        "No la uses para límites de alarma o disparo (consultar_equipos, hoja de datos vigente), valores medidos "
        "(consultar_historial_sensor), stock o costo de repuestos (consultar_repuestos) ni el catálogo de tareas "
        "(consultar_tareas): esos números salen de la planta, no de los manuales.\n"
        "Ya filtra la Rev. C del manual de la bomba (reemplazada) y las secciones que no aplican a PIA-3 (otros "
        "modelos, PIA-1, PIA-2, opcionales, instalación). Devuelve como mucho k fragmentos (por defecto 4)."
        + GARANTIAS,
        EntradaManuales, SalidaManuales, buscar_en_manuales),
]
HERRAMIENTAS: dict[str, Herramienta] = {h.nombre: h for h in _LISTA}


def describir_validacion(error: ValidationError, entrada: type[BaseModel]) -> str:
    """Errores de Pydantic en castellano y con la corrección a mano."""
    partes = []
    for e in error.errors():
        campo = ".".join(str(p) for p in e["loc"])
        mensaje = e["msg"].removeprefix("Value error, ")
        if e["type"] == "extra_forbidden":
            partes.append(f"el campo '{campo}' no existe (campos válidos: {', '.join(entrada.model_fields)})")
        elif e["type"] == "missing":
            partes.append(f"falta el campo obligatorio '{campo}'")
        elif e["type"] == "literal_error":
            partes.append(f"{campo}: '{e['input']}' no es válido; valores permitidos: {e['ctx']['expected']}")
        elif e["type"].startswith(("datetime_", "date_")):
            partes.append(f"{campo}: '{e['input']}' no es una fecha ISO 8601 válida (p. ej. "
                          f"'2026-11-10T07:00:00-03:00')")
        else:
            partes.append(f"{campo}: {mensaje}" if campo else mensaje)
    return "Argumentos inválidos: " + "; ".join(partes) + "."


async def ejecutar(nombre: str, argumentos: dict[str, Any] | BaseModel, recursos: Recursos, *,
                   timeout_s: float = TIMEOUT_TOOL_S) -> BaseModel:
    """Corre una tool y devuelve su salida o un `ErrorHerramienta`. No lanza."""
    h = HERRAMIENTAS.get(nombre)
    if h is None:
        return ErrorHerramienta(codigo="HERRAMIENTA_INEXISTENTE", reintentable=False,
                                mensaje=f"No existe la tool '{nombre}'. Tools: {', '.join(HERRAMIENTAS)}.")
    try:
        datos = argumentos.model_dump(exclude_unset=True) if isinstance(argumentos, BaseModel) else argumentos
        entrada = h.entrada.model_validate(datos)
    except ValidationError as e:
        return ErrorHerramienta(codigo="ARGUMENTOS_INVALIDOS", mensaje=describir_validacion(e, h.entrada),
                                reintentable=False)
    try:
        async with asyncio.timeout(timeout_s):
            return await h.funcion(entrada, recursos)
    except (FalloConsulta, ErrorPlanta) as e:
        return ErrorHerramienta(codigo=e.codigo, mensaje=e.mensaje, reintentable=e.reintentable)
    except ErrorMateriales as e:
        return ErrorHerramienta(codigo="MATERIALES_NO_DISPONIBLES", mensaje=str(e), reintentable=False)
    except TimeoutError:
        return ErrorHerramienta(codigo="TIMEOUT", reintentable=True,
                                mensaje=f"La consulta {nombre} superó {timeout_s:g} s. Probá de nuevo o seguí sin "
                                        f"el dato.")
    except Exception:
        log.exception("Falla inesperada en la tool %s", nombre)
        return ErrorHerramienta(codigo="ERROR_INTERNO", reintentable=False,
                                mensaje=f"Falla interna en {nombre}. Seguí sin este dato y avisá.")


def a_json(resultado: BaseModel) -> str:
    """Texto compacto para el modelo: sin los campos vacíos, que en estas salidas son muchos."""
    return resultado.model_dump_json(exclude_none=True)


def herramientas_langchain(recursos: Recursos | None = None) -> list[StructuredTool]:
    """Las tools como `StructuredTool` asíncronas (args_schema = contrato de entrada).

    Una falla vuelve como `ToolMessage` con `status="error"` y el JSON del `ErrorHerramienta` como contenido.
    """
    recursos = recursos or Recursos()

    def crear(h: Herramienta) -> StructuredTool:
        async def correr(**argumentos: Any) -> str:
            resultado = await ejecutar(h.nombre, argumentos, recursos)
            if isinstance(resultado, ErrorHerramienta):
                raise ToolException(a_json(resultado))
            return a_json(resultado)

        def error_de_validacion(e: ValidationError) -> str:
            return a_json(ErrorHerramienta(codigo="ARGUMENTOS_INVALIDOS", mensaje=describir_validacion(e, h.entrada),
                                           reintentable=False))

        return StructuredTool.from_function(coroutine=correr, name=h.nombre, description=h.descripcion,
                                            args_schema=h.entrada, handle_tool_error=True,
                                            handle_validation_error=error_de_validacion)

    return [crear(h) for h in HERRAMIENTAS.values()]
