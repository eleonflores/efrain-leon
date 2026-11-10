"""Contratos de las tools de consulta: entrada y salida en Pydantic estricto.

Todos los modelos llevan `extra="forbid"` (en el JSON Schema sale `additionalProperties: false`): un campo que el
modelo inventa es un error que se le devuelve para que corrija, no algo que se ignora en silencio. Las descripciones
de los campos son documentación para el modelo: dicen el formato y traen un ejemplo.

Los valores cerrados de la entrada (tipo de equipo, variable de sensor) van como `Literal`, así el esquema los
enumera. En la salida los textos que vienen de la planta quedan como `str`: si la planta agrega un tipo nuevo, la
consulta no se rompe por eso.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sistema.integraciones.planta_api import a_hora_planta

TipoEquipo = Literal["bomba", "filtro", "tanque", "caudalimetro"]
VariableSensor = Literal["presion_succion", "presion_descarga", "temperatura_aceite", "vibracion",
                         "presion_diferencial", "caudal"]
CodigoError = Literal[
    "ARGUMENTOS_INVALIDOS", "HERRAMIENTA_INEXISTENTE", "EQUIPO_INEXISTENTE", "SENSOR_INEXISTENTE",
    "REPUESTO_INEXISTENTE", "TAREA_INEXISTENTE", "PLANTA_TIMEOUT", "PLANTA_NO_DISPONIBLE", "PLANTA_RECHAZO",
    "RESPUESTA_INVALIDA", "MATERIALES_NO_DISPONIBLES", "RAG_NO_DISPONIBLE", "TIMEOUT", "ERROR_INTERNO",
]
DocumentoManual = Literal["TX350-D", "FC48-3", "MBP-4", "CT-SVP-2025", "CERT-EJ", "historial"]

FECHA = ("Fecha y hora ISO 8601 con offset, p. ej. '2026-11-10T07:00:00-03:00'. Sin offset se toma como hora de la "
         "planta (-03:00).")
EQUIPO = "TAG del equipo, p. ej. 'B-102'. También acepta el nombre informal de campo ('la dos', 'el filtro B')."
CODIGO = r"^[A-Za-z0-9][A-Za-z0-9-]{1,30}$"


class Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorHerramienta(Estricto):
    """Resultado de una consulta que no se pudo hacer. Nunca se lanza: se devuelve."""

    codigo: CodigoError = Field(description="Código estable del error, p. ej. 'EQUIPO_INEXISTENTE'.")
    mensaje: str = Field(description="Qué pasó y qué hacer para corregirlo.")
    reintentable: bool = Field(description="true: falla transitoria, puede andar más tarde con los mismos "
                                           "argumentos. false: hay que cambiar los argumentos.")


def _orden(desde: datetime | None, hasta: datetime | None) -> None:
    if desde is not None and hasta is not None and a_hora_planta(desde) >= a_hora_planta(hasta):
        raise ValueError(f"'desde' ({desde.isoformat()}) tiene que ser anterior a 'hasta' ({hasta.isoformat()})")


# ---------------------------------------------------------------- consultar_equipos

class EntradaEquipos(Estricto):
    tag: str | None = Field(None, min_length=1, max_length=40,
                            description=EQUIPO + " Sin tag: todos los equipos.")
    tipo: TipoEquipo | None = Field(None, description="Filtra por tipo de equipo, p. ej. 'bomba'.")


class SensorEquipo(Estricto):
    variable: str = Field(description="Variable del sensor conectado, p. ej. 'presion_descarga'.")
    unidad: str = Field(description="Unidad en que la guarda el historiador, p. ej. 'kg/cm2'.")
    alarma_baja: float | None = Field(None, description="Alarma por bajo (hoja de datos). null si no tiene.")
    alarma_alta: float | None = Field(None, description="Alarma por alto (hoja de datos). null si no tiene.")
    disparo: float | None = Field(None, description="Valor de disparo (parada automática). null si no tiene.")


class EquipoInfo(Estricto):
    tag: str
    tipo: str
    descripcion: str | None = None
    fabricante: str | None = None
    modelo: str | None = None
    nombres_informales: list[str] = Field(description="Cómo lo nombran los operadores, p. ej. ['la dos'].")
    unidad_manometro_local: str | None = Field(None, description="Unidad del manómetro local que lee el operador "
                                                                 "(solo bombas): 'kg/cm2', 'psi' o 'bar'.")
    rol_inicial: str | None = Field(None, description="Rol al arrancar la planta: 'servicio' o 'reserva'.")
    caudal_nominal_m3d: float | None = None
    cartuchos: int | None = None
    altura_m: float | None = None
    diametro_m: float | None = None
    sensores: list[SensorEquipo] = Field(description="Sensores conectados (los que tienen historial).")
    lecturas_locales: list[str] = Field(description="Lo que el operador lee en la recorrida (no está en el "
                                                    "historiador).")


class SalidaEquipos(Estricto):
    equipos: list[EquipoInfo]


# ---------------------------------------------------------------- consultar_historial_sensor

class EntradaHistorialSensor(Estricto):
    tag: str = Field(min_length=1, max_length=40, description=EQUIPO)
    variable: VariableSensor = Field(description="Sensor conectado. Bombas: presion_succion, presion_descarga, "
                                                 "temperatura_aceite, vibracion. Filtros: presion_diferencial. "
                                                 "FT-401: caudal.")
    desde: datetime = Field(description="Inicio del rango (inclusive). " + FECHA)
    hasta: datetime | None = Field(None, description="Fin del rango (inclusive). Sin hasta: hasta la última muestra. "
                                                     + FECHA)
    max_puntos: int = Field(24, ge=2, le=200, description="Máximo de puntos de la serie submuestreada, p. ej. 24.")

    @model_validator(mode="after")
    def _rango(self) -> "EntradaHistorialSensor":
        _orden(self.desde, self.hasta)
        return self


class LimitesAlarma(Estricto):
    alarma_baja: float | None = None
    alarma_alta: float | None = None
    disparo: float | None = None


class ResumenSerie(Estricto):
    n_muestras: int = Field(description="Muestras en el rango (una por minuto).")
    n_sin_valor: int = Field(description="Muestras con valor null (sensor sin dato).")
    minimo: float | None = None
    maximo: float | None = None
    promedio: float | None = None
    p5: float | None = Field(None, description="Percentil 5.")
    p95: float | None = Field(None, description="Percentil 95.")
    ultimo_ts: datetime | None = Field(None, description="Hora de la última muestra del rango (hora de planta).")
    ultimo_valor: float | None = Field(None, description="Valor de la última muestra (null si no tenía dato).")
    muestras_sobre_alarma_alta: int = Field(0, description="Muestras con valor >= alarma alta.")
    muestras_bajo_alarma_baja: int = Field(0, description="Muestras con valor <= alarma baja.")


class PuntoSerie(Estricto):
    ts: datetime = Field(description="Inicio del tramo (hora de planta).")
    valor: float | None = Field(description="Promedio del tramo (null si el tramo no tiene datos).")


class SalidaHistorialSensor(Estricto):
    tag: str
    variable: str
    unidad: str
    desde: datetime
    hasta: datetime | None
    limites: LimitesAlarma
    resumen: ResumenSerie
    minutos_por_punto: int = Field(description="Muestras (minutos) que promedia cada punto de la serie.")
    serie: list[PuntoSerie] = Field(description="Serie submuestreada, a lo sumo max_puntos puntos, de vieja a nueva.")
    observacion: str | None = None


# ---------------------------------------------------------------- consultar_historial_ordenes

class EntradaHistorialOrdenes(Estricto):
    equipo: str | None = Field(None, min_length=1, max_length=40,
                               description=EQUIPO + " 'PLANTA' trae las órdenes generales (p. ej. la medición mensual "
                                                    "de vibraciones). Sin equipo: todas.")
    desde: datetime | None = Field(None, description="Órdenes con fecha de aviso desde este momento. " + FECHA)
    hasta: datetime | None = Field(None, description="Órdenes con fecha de aviso hasta este momento. " + FECHA)
    tarea: str | None = Field(None, pattern=CODIGO, description="Solo las órdenes que incluyen esta tarea del "
                                                                "catálogo, p. ej. 'T-B-EMP'.")
    limite: int = Field(10, ge=1, le=50, description="Máximo de órdenes a devolver (las más nuevas), p. ej. 10.")

    @model_validator(mode="after")
    def _rango(self) -> "EntradaHistorialOrdenes":
        _orden(self.desde, self.hasta)
        return self


class RepuestoUsado(Estricto):
    codigo: str
    cantidad: float


class OrdenHistorica(Estricto):
    id: str
    fecha: datetime = Field(description="Fecha del aviso (hora de planta).")
    equipo: str
    tipo: str | None = Field(None, description="'correctiva', 'por condición', 'predictiva', ...")
    tareas: list[str] = Field(description="Códigos de tarea del catálogo, p. ej. ['T-B-EMP'].")
    ejecutor: str | None = Field(None, description="'propio' o el nombre de la contratista.")
    estado: str | None = None
    origen: str | None = Field(None, description="'archivo' (histórico) o 'simulador' (recientes).")
    aviso: str | None = Field(None, description="Texto libre del aviso, como lo escribió el operador.")
    trabajo_realizado: str | None = Field(None, description="Texto libre del cierre, como lo escribió el técnico.")
    descripcion: str | None = None
    codigo_falla: str | None = Field(None, description="Código de falla, p. ej. 'F01'.")
    repuestos: list[RepuestoUsado] = []
    horas: float | None = None
    fecha_inicio: datetime | None = None
    fecha_cierre: datetime | None = None
    solicitante: str | None = None
    tecnico: str | None = None


class SalidaHistorialOrdenes(Estricto):
    equipo: str | None
    total: int = Field(description="Órdenes que cumplen los filtros. Si es mayor que devueltas, acotá la consulta.")
    devueltas: int
    ordenes: list[OrdenHistorica] = Field(description="De la más nueva a la más vieja.")


# ---------------------------------------------------------------- consultar_repuestos

class EntradaRepuestos(Estricto):
    equipo: str | None = Field(None, min_length=1, max_length=40,
                               description=EQUIPO + " Devuelve la lista de materiales del equipo.")
    codigo: str | None = Field(None, pattern=CODIGO, description="Código de repuesto, p. ej. 'TX-EMP-KIT'.")

    @model_validator(mode="after")
    def _uno_solo(self) -> "EntradaRepuestos":
        if self.equipo is not None and self.codigo is not None:
            raise ValueError("pasá 'equipo' o 'codigo', no los dos (sin ninguno: inventario completo)")
        return self


class RepuestoInfo(Estricto):
    codigo: str
    nombre: str
    unidad: str
    costo_unitario_usd: float
    stock_yacimiento: int = Field(description="Stock en el almacén de la planta (disponible ya).")
    stock_central: int = Field(description="Stock en el almacén central de Comodoro Rivadavia (3 a 5 días).")
    equipos: list[str] = Field(description="Equipos cuya lista de materiales lo incluye.")


class SalidaRepuestos(Estricto):
    equipo: str | None
    repuestos: list[RepuestoInfo]
    observacion: str | None = None


# ---------------------------------------------------------------- consultar_tareas

class EntradaTareas(Estricto):
    equipo: str | None = Field(None, min_length=1, max_length=40,
                               description=EQUIPO + " Devuelve sus tareas estándar más todas las no estándar.")
    codigo: str | None = Field(None, pattern=CODIGO, description="Código de tarea, p. ej. 'T-B-EMP'.")
    estandar: bool | None = Field(None, description="true: solo estándar. false: solo no estándar. Sin valor: ambas.")


class RepuestoDeTareaInfo(Estricto):
    codigo: str
    nombre: str | None = Field(None, description="null si el código no está en el inventario.")
    cantidad: float
    costo_unitario_usd: float | None = None
    costo_usd: float | None = Field(None, description="cantidad × costo unitario.")
    stock_yacimiento: int | None = None
    stock_central: int | None = None
    alcanza_stock_yacimiento: bool | None = Field(None, description="true si el almacén de la planta tiene la "
                                                                    "cantidad que pide la tarea.")


class TareaInfo(Estricto):
    codigo: str
    nombre: str
    estandar: bool = Field(description="false: tarea no estándar, siempre requiere aprobación del planificador.")
    equipos: list[str] = Field(description="Equipos a los que aplica. Vacío en las no estándar (sin asignar).")
    detiene_equipo: bool
    horas: float
    ejecutor: Literal["propio", "contratista"]
    repuestos: list[RepuestoDeTareaInfo] | None = Field(None, description="null si el catálogo no los lista.")
    costo_total_usd: float | None = Field(None, description="Suma de los repuestos en USD (sin mano de obra). "
                                                            "null si el catálogo no lista los repuestos.")


class SalidaTareas(Estricto):
    equipo: str | None
    tareas: list[TareaInfo]


# ---------------------------------------------------------------- buscar_en_manuales

class EntradaManuales(Estricto):
    pregunta: str = Field(min_length=3, max_length=400,
                          description="Qué buscar, con las palabras de la planta y los códigos tal cual, p. ej. "
                                      "'la bomba hace ruido a piedras y la succión está baja', 'qué es la TX-T07', "
                                      "'qué se encontró antes cuando la B-103 perdió por la empaquetadura'.")
    documento: DocumentoManual | None = Field(
        None, description="Limita la búsqueda a un documento: 'TX350-D' (bomba Trimax TX-350, Rev. D vigente), "
                          "'FC48-3' (filtro Filtrapat FC-48), 'MBP-4' (buenas prácticas de la operadora), "
                          "'CT-SVP-2025' (contrato con Servipat), 'CERT-EJ' (cierres de ejemplo de Servipat), "
                          "'historial' (órdenes de trabajo). Sin documento: todos.")
    equipo: str | None = Field(None, min_length=1, max_length=40,
                               description=EQUIPO + " Deja solo lo que aplica a ese equipo (manuales y órdenes).")
    k: int = Field(4, ge=1, le=8, description="Cantidad de fragmentos a devolver, p. ej. 4.")


class FragmentoManual(Estricto):
    cita: str = Field(description="Cómo citarlo en la conclusión, p. ej. 'TX350-D §3.2' o 'historial OT-25-0026'.")
    documento: str = Field(description="Documento, p. ej. 'TX350-D' o 'historial'.")
    revision: str | None = Field(None, description="Revisión del documento, p. ej. 'D'.")
    seccion: str = Field(description="Número de sección ('3.2') o de orden ('OT-25-0026').")
    titulo: str
    pagina: int | None = Field(None, description="Página del PDF del documento.")
    fabricante: str | None = Field(None, description="Emisor del documento (fabricante u operadora).")
    texto: str = Field(description="Texto de la sección u orden, recortado a unos 700 caracteres.")
    puntaje: float = Field(description="Puntaje de la búsqueda híbrida (RRF): solo sirve para ordenar.")


class SalidaManuales(Estricto):
    pregunta: str
    modo: Literal["hibrida", "vectores", "lexica"] = Field(
        description="'hibrida' (semántica + texto + códigos). 'lexica' si el modelo de embeddings no estaba "
                    "disponible: la búsqueda anduvo, pero solo por palabras.")
    citas: list[str] = Field(description="Las citas de los fragmentos, en orden de relevancia.")
    fragmentos: list[FragmentoManual] = Field(description="Del más relevante al menos relevante. Solo lo vigente y "
                                                          "lo que aplica a PIA-3.")
    observacion: str | None = None
