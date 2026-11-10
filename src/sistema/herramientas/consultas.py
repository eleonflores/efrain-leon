"""Las cinco consultas de solo lectura: equipos, historial de un sensor, historial de órdenes, repuestos y tareas.

Cada una es una función asíncrona `(entrada, recursos) -> salida` que ya recibe la entrada validada por Pydantic
(capa sintáctica) y hace la validación semántica antes de tocar la red: el equipo existe, la variable es un sensor
de ese equipo, el código está en el catálogo. Cuando algo no cierra lanza `FalloConsulta` con un mensaje que dice qué
hacer; el registro lo convierte en un `ErrorHerramienta` para el modelo. Ninguna escribe nada.

El historiador guarda una muestra por minuto de 45 días: nunca se devuelve crudo. Sale un resumen y una serie
promediada por tramos, acotada a `max_puntos`.
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import ValidationError

from sistema.dominio.planta import Planta
from sistema.herramientas.materiales import CatalogoMateriales, MaterialesYaml, RepositorioMateriales, Tarea
from sistema.herramientas.modelos import (
    EntradaEquipos, EntradaHistorialOrdenes, EntradaHistorialSensor, EntradaRepuestos, EntradaTareas, EquipoInfo,
    LimitesAlarma, OrdenHistorica, PuntoSerie, RepuestoDeTareaInfo, RepuestoInfo, ResumenSerie, SalidaEquipos,
    SalidaHistorialOrdenes, SalidaHistorialSensor, SalidaRepuestos, SalidaTareas, SensorEquipo, TareaInfo,
)
from sistema.integraciones.planta_api import ClientePlanta, a_hora_planta
from sistema.rag.busqueda import BuscadorManuales

log = logging.getLogger(__name__)

PLANTA = "PLANTA"
LECTURAS_POR_TIPO = {"bomba": "bombas", "filtro": "filtros", "tanque": "tanque"}


class FalloConsulta(Exception):
    def __init__(self, codigo: str, mensaje: str, reintentable: bool = False):
        super().__init__(mensaje)
        self.codigo, self.mensaje, self.reintentable = codigo, mensaje, reintentable


@dataclass
class Recursos:
    """Lo que necesitan las consultas para correr. En los tests se arma con dobles."""

    planta: ClientePlanta = field(default_factory=ClientePlanta)
    materiales: RepositorioMateriales = field(default_factory=MaterialesYaml)
    # Búsqueda en manuales (RAG). Conecta con Postgres y carga el modelo recién en la primera consulta.
    manuales: BuscadorManuales = field(default_factory=BuscadorManuales)


def _clave(texto: str) -> str:
    return re.sub(r"[\s_-]", "", texto.upper())


@dataclass
class CatalogoPlanta:
    definicion: dict
    planta: Planta

    @classmethod
    def desde_definicion(cls, d: dict) -> "CatalogoPlanta":
        return cls(d, Planta.desde_definicion(d))

    def resolver(self, dicho: str, *, admite_planta: bool = False) -> str:
        """TAG exacto, TAG sin guion o con otra capitalización ('b102'), o nombre informal ('la dos')."""
        if admite_planta and _clave(dicho) == PLANTA:
            return PLANTA
        tag = next((t for t in self.planta.equipos if _clave(t) == _clave(dicho)), None) or self.planta.resolver(dicho)
        if tag is None:
            validos = ", ".join(f"{t} ({e.nombres[0]})" if e.nombres else t for t, e in self.planta.equipos.items())
            extra = " o 'PLANTA' para las órdenes generales" if admite_planta else ""
            raise FalloConsulta("EQUIPO_INEXISTENTE", f"No existe el equipo '{dicho}' (o el nombre es ambiguo). "
                                                      f"Usá un TAG exacto: {validos}{extra}.")
        return tag

    def sensores(self, tag: str) -> list[dict]:
        return [s for s in self.definicion.get("sensores", []) if s.get("tag") == tag]

    def lecturas_locales(self, tipo: str) -> list[str]:
        return list((self.definicion.get("lecturas_locales") or {}).get(LECTURAS_POR_TIPO.get(tipo, tipo), []))


async def _catalogo_planta(r: Recursos) -> CatalogoPlanta:
    return CatalogoPlanta.desde_definicion(await r.planta.definicion())


def _redondo(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


# ---------------------------------------------------------------- equipos

async def consultar_equipos(e: EntradaEquipos, r: Recursos) -> SalidaEquipos:
    cat = await _catalogo_planta(r)
    tag = cat.resolver(e.tag) if e.tag else None
    equipos = []
    for d in cat.definicion["equipos"]:
        if (tag and d["tag"] != tag) or (e.tipo and d.get("tipo") != e.tipo):
            continue
        equipos.append(EquipoInfo(
            tag=d["tag"], tipo=d.get("tipo", ""), descripcion=d.get("descripcion"), fabricante=d.get("fabricante"),
            modelo=d.get("modelo"), nombres_informales=list(d.get("nombres", [])),
            unidad_manometro_local=(d.get("manometro_local") or {}).get("unidad"), rol_inicial=d.get("rol_inicial"),
            caudal_nominal_m3d=d.get("caudal_nominal_m3d"), cartuchos=d.get("cartuchos"), altura_m=d.get("altura_m"),
            diametro_m=d.get("diametro_m"),
            sensores=[SensorEquipo(variable=s["variable"], unidad=s.get("unidad", ""), alarma_baja=s.get("alarma_baja"),
                                   alarma_alta=s.get("alarma_alta"), disparo=s.get("disparo"))
                      for s in cat.sensores(d["tag"])],
            lecturas_locales=cat.lecturas_locales(d.get("tipo", ""))))
    return SalidaEquipos(equipos=equipos)


# ---------------------------------------------------------------- historial de un sensor

def _puntos(crudos: list[dict], desde: datetime, hasta: datetime | None) -> list[tuple[datetime, float | None]]:
    """Parsea `[{ts, valor}]` y descarta lo que caiga fuera del rango (resguardo ante el filtro de la API)."""
    puntos = []
    for p in crudos:
        try:
            ts = a_hora_planta(datetime.fromisoformat(p["ts"]))
            valor = None if p.get("valor") is None else float(p["valor"])
        except (KeyError, TypeError, ValueError):
            continue
        if ts >= desde and (hasta is None or ts <= hasta):
            puntos.append((ts, valor))
    puntos.sort(key=lambda p: p[0])
    return puntos


def _submuestrear(puntos: list[tuple[datetime, float | None]], max_puntos: int) -> tuple[int, list[PuntoSerie]]:
    tramo = max(1, math.ceil(len(puntos) / max_puntos))
    serie = []
    for i in range(0, len(puntos), tramo):
        valores = [v for _, v in puntos[i:i + tramo] if v is not None]
        serie.append(PuntoSerie(ts=puntos[i][0], valor=_redondo(statistics.fmean(valores)) if valores else None))
    return tramo, serie


def _resumen(puntos: list[tuple[datetime, float | None]], lim: LimitesAlarma) -> ResumenSerie:
    valores = [v for _, v in puntos if v is not None]
    resumen = ResumenSerie(n_muestras=len(puntos), n_sin_valor=len(puntos) - len(valores))
    if puntos:
        resumen.ultimo_ts, resumen.ultimo_valor = puntos[-1]
    if valores:
        cuantiles = statistics.quantiles(valores, n=20, method="inclusive") if len(valores) > 1 else [valores[0]] * 19
        resumen.minimo, resumen.maximo = min(valores), max(valores)
        resumen.promedio = _redondo(statistics.fmean(valores))
        resumen.p5, resumen.p95 = _redondo(cuantiles[0]), _redondo(cuantiles[-1])
        if lim.alarma_alta is not None:
            resumen.muestras_sobre_alarma_alta = sum(v >= lim.alarma_alta for v in valores)
        if lim.alarma_baja is not None:
            resumen.muestras_bajo_alarma_baja = sum(v <= lim.alarma_baja for v in valores)
    return resumen


async def consultar_historial_sensor(e: EntradaHistorialSensor, r: Recursos) -> SalidaHistorialSensor:
    cat = await _catalogo_planta(r)
    tag = cat.resolver(e.tag)
    sensores = cat.sensores(tag)
    sensor = next((s for s in sensores if s.get("variable") == e.variable), None)
    if sensor is None:
        disponibles = ", ".join(s["variable"] for s in sensores)
        donde = (f"Sensores de {tag}: {disponibles}." if disponibles else
                 f"{tag} no tiene sensores conectados: sus valores solo salen de las lecturas de la recorrida.")
        raise FalloConsulta("SENSOR_INEXISTENTE", f"{tag} no tiene el sensor '{e.variable}' conectado. {donde}")

    desde = a_hora_planta(e.desde)
    hasta = a_hora_planta(e.hasta) if e.hasta else None
    puntos = _puntos(await r.planta.historian(tag, e.variable, desde, hasta), desde, hasta)
    limites = LimitesAlarma(alarma_baja=sensor.get("alarma_baja"), alarma_alta=sensor.get("alarma_alta"),
                            disparo=sensor.get("disparo"))
    tramo, serie = _submuestrear(puntos, e.max_puntos)
    observacion = None
    if not puntos:
        observacion = (f"No hay muestras de {tag}/{e.variable} en ese rango. El historiador guarda una muestra por "
                       f"minuto de los últimos 45 días del reloj de la planta: revisá desde y hasta.")
    return SalidaHistorialSensor(tag=tag, variable=e.variable, unidad=sensor.get("unidad", ""), desde=desde,
                                 hasta=hasta, limites=limites, resumen=_resumen(puntos, limites),
                                 minutos_por_punto=tramo, serie=serie, observacion=observacion)


# ---------------------------------------------------------------- historial de órdenes

def _parsear_orden(o: dict) -> OrdenHistorica | None:
    try:
        datos = {k: o.get(k) for k in OrdenHistorica.model_fields if k in o}
        datos["fecha"] = o.get("fecha") or o.get("fecha_aviso")
        datos["tareas"] = o.get("tareas") or []
        datos["repuestos"] = o.get("repuestos") or []
        orden = OrdenHistorica.model_validate(datos)
    except ValidationError as e:
        log.warning("Orden %s descartada por formato inválido: %s", o.get("id"), e.errors()[0]["msg"])
        return None
    orden.fecha = a_hora_planta(orden.fecha)
    return orden


async def consultar_historial_ordenes(e: EntradaHistorialOrdenes, r: Recursos) -> SalidaHistorialOrdenes:
    equipo = (await _catalogo_planta(r)).resolver(e.equipo, admite_planta=True) if e.equipo else None
    desde = a_hora_planta(e.desde) if e.desde else None
    hasta = a_hora_planta(e.hasta) if e.hasta else None
    tarea = e.tarea.upper() if e.tarea else None
    ordenes = [o for o in map(_parsear_orden, await r.planta.historial_ordenes(equipo, desde, hasta))
               if o is not None and (equipo is None or o.equipo == equipo)
               and (desde is None or o.fecha >= desde) and (hasta is None or o.fecha <= hasta)
               and (tarea is None or tarea in o.tareas)]
    ordenes.sort(key=lambda o: o.fecha, reverse=True)
    elegidas = ordenes[:e.limite]
    return SalidaHistorialOrdenes(equipo=equipo, total=len(ordenes), devueltas=len(elegidas), ordenes=elegidas)


# ---------------------------------------------------------------- repuestos

async def _resolver_equipo_materiales(dicho: str, r: Recursos, mat: CatalogoMateriales) -> str:
    """Primero contra los TAG del catálogo de materiales (sin red); si no, contra la planta (nombres informales)."""
    conocidos = set(mat.lista_materiales) | {t for tarea in mat.tareas for t in tarea.equipos}
    tag = next((t for t in conocidos if _clave(t) == _clave(dicho)), None)
    return tag or (await _catalogo_planta(r)).resolver(dicho)


def _usos(mat: CatalogoMateriales) -> dict[str, list[str]]:
    usos: dict[str, list[str]] = {}
    for equipo, codigos in mat.lista_materiales.items():
        for codigo in codigos:
            usos.setdefault(codigo, []).append(equipo)
    return usos


def _repuesto_inexistente(codigo: str, mat: CatalogoMateriales) -> FalloConsulta:
    return FalloConsulta("REPUESTO_INEXISTENTE", f"No existe el repuesto '{codigo}'. Códigos válidos: "
                                                 f"{', '.join(mat.repuestos)}.")


async def consultar_repuestos(e: EntradaRepuestos, r: Recursos) -> SalidaRepuestos:
    mat = await r.materiales.cargar()
    usos = _usos(mat)
    equipo, observacion = None, None
    if e.codigo:
        codigos = [e.codigo.upper()]
        if codigos[0] not in mat.repuestos:
            raise _repuesto_inexistente(e.codigo, mat)
    elif e.equipo:
        equipo = await _resolver_equipo_materiales(e.equipo, r, mat)
        codigos = mat.lista_materiales.get(equipo, [])
        if not codigos:
            observacion = f"{equipo} no tiene lista de materiales cargada."
    else:
        codigos = list(mat.repuestos)
    repuestos = []
    for codigo in codigos:
        rep = mat.repuestos.get(codigo)
        if rep is None:
            log.warning("La lista de materiales nombra el repuesto %s, que no está en el inventario", codigo)
            continue
        repuestos.append(RepuestoInfo(codigo=rep.codigo, nombre=rep.nombre, unidad=rep.unidad,
                                      costo_unitario_usd=rep.costo_usd, stock_yacimiento=rep.stock.yacimiento,
                                      stock_central=rep.stock.central, equipos=usos.get(codigo, [])))
    return SalidaRepuestos(equipo=equipo, repuestos=repuestos, observacion=observacion)


# ---------------------------------------------------------------- tareas

def _tarea_info(t: Tarea, mat: CatalogoMateriales) -> TareaInfo:
    repuestos, total = None, None
    if t.repuestos is not None:
        repuestos, total = [], 0.0
        for rt in t.repuestos:
            rep = mat.repuestos.get(rt.codigo)
            if rep is None:
                repuestos.append(RepuestoDeTareaInfo(codigo=rt.codigo, cantidad=rt.cantidad))
                total = None
                continue
            costo = rt.cantidad * rep.costo_usd
            repuestos.append(RepuestoDeTareaInfo(
                codigo=rt.codigo, nombre=rep.nombre, cantidad=rt.cantidad, costo_unitario_usd=rep.costo_usd,
                costo_usd=_redondo(costo), stock_yacimiento=rep.stock.yacimiento, stock_central=rep.stock.central,
                alcanza_stock_yacimiento=rep.stock.yacimiento >= rt.cantidad))
            total = None if total is None else total + costo
    return TareaInfo(codigo=t.codigo, nombre=t.nombre, estandar=t.estandar, equipos=t.equipos,
                     detiene_equipo=t.detiene, horas=t.horas, ejecutor=t.ejecutor, repuestos=repuestos,
                     costo_total_usd=_redondo(total))


async def consultar_tareas(e: EntradaTareas, r: Recursos) -> SalidaTareas:
    mat = await r.materiales.cargar()
    tareas = mat.tareas
    if e.codigo:
        codigo = e.codigo.upper()
        tareas = [t for t in tareas if t.codigo == codigo]
        if not tareas:
            codigos = ", ".join(dict.fromkeys(t.codigo for t in mat.tareas))
            raise FalloConsulta("TAREA_INEXISTENTE", f"No existe la tarea '{e.codigo}'. Códigos válidos: {codigos}.")
    equipo = await _resolver_equipo_materiales(e.equipo, r, mat) if e.equipo else None
    if equipo:
        tareas = [t for t in tareas if not t.estandar or equipo in t.equipos]
    if e.estandar is not None:
        tareas = [t for t in tareas if t.estandar == e.estandar]
    return SalidaTareas(equipo=equipo, tareas=[_tarea_info(t, mat) for t in tareas])
