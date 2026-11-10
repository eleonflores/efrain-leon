"""Corpus documental de PIA-3: fragmentos con los metadatos que el RAG necesita para filtrar y citar."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[3]
RUTAS_POR_DEFECTO = (RAIZ_REPO / "datos" / "documentos", Path("/app/datos/documentos"))

# Clave de la sección o de su capítulo → motivo por el que no aplica a PIA-3.
NO_APLICA_POR_CLAVE = {
    "familia": "compara los modelos de la familia (TX-250, TX-500, FC-24, FC-96); los datos de PIA-3 están en las "
               "especificaciones del modelo",
    "limites-otros": "límites de otros modelos de la familia (TX-250, TX-500)",
    "limites-otras": "límites de otras plantas (PIA-1, PIA-2)",
    "otras-plantas": "secciones de las plantas PIA-1 y PIA-2",
    "instalacion": "instalación inicial, no operación ni mantenimiento",
    "preservacion": "equipos en depósito o fuera de servicio por meses",
    "transporte": "transporte y recepción, no aplica a la operación",
    "opcionales": "opcionales que los equipos de PIA-3 no tienen",
}
TIPO_HISTORIAL = "historial"
_CABECERA_ORDEN = re.compile(r"^(OT-\d{2}-\d{4}) · (\d{4}-\d{2}-\d{2}) · ([A-Z0-9-]+) · (.*?) · (.*)$", re.M)

# MBP-4 §2.2: cómo se nombra cada equipo en campo.
NOMBRE_EQUIPO = {
    "B-101": "bomba 1, la uno", "B-102": "bomba 2, la dos", "B-103": "bomba 3, la tres, la del fondo",
    "F-201A": "filtro A, el primario", "F-201B": "filtro B, el secundario", "TK-301": "tanque pulmón",
    "FT-401": "caudalímetro del colector", "PLANTA": "toda la planta",
}
# MBP-4 §13.1 y §13.2: nombre de cada tarea.
NOMBRE_TAREA = {
    "T-B-EMP": "cambio de empaquetadura", "T-B-VAL": "cambio de válvulas de succión y descarga",
    "T-B-ACE": "reposición de aceite del cárter", "T-B-COR": "cambio de correas", "T-F-CAR": "cambio de cartuchos",
    "T-I-CAL": "calibración de instrumento", "T-B-ROD": "cambio de rodamientos del cigüeñal",
    "T-B-ALI": "alineación láser de acople", "I-VIB": "análisis de vibraciones con colector",
    "I-VAL": "revisión de válvulas", "NO-ESTANDAR": "tarea no estándar",
}
# MBP-4 §4.4 (abreviaturas de la planilla) más las que aparecen en el texto libre de las órdenes.
ABREVIATURAS = {
    "cbio": "cambio", "dif": "diferencial", "empaq": "empaquetadura", "lts": "litros", "hs": "horas",
    "bba": "bomba", "bbas": "bombas", "q": "que", "porq": "porque", "mant": "mantenimiento", "pres": "presión",
    "succ": "succión", "max": "máximo", "ext": "externa", "x": "por", "c/": "con", "s/": "sin",
    "s/n": "sin novedad", "fa": "filtro A primario", "fb": "filtro B secundario", "b1": "bomba 1",
    "b2": "bomba 2", "b3": "bomba 3",
}
_ABREVIATURA = re.compile(r"(?<![\w/])(" + "|".join(sorted(map(re.escape, ABREVIATURAS), key=len, reverse=True))
                          + r")(?![\w/])", re.IGNORECASE)


def expandir_abreviaturas(texto: str) -> str:
    return _ABREVIATURA.sub(lambda m: ABREVIATURAS[m.group(1).lower()], texto)


def texto_busqueda_orden(texto: str) -> str:
    """La orden en palabras para buscar: cabecera explicada y abreviaturas expandidas."""
    m = _CABECERA_ORDEN.match(texto)
    if not m:
        return expandir_abreviaturas(texto)
    ot, fecha, equipo, tareas, ejecutor = m.groups()
    nombres = [NOMBRE_TAREA[t] for t in tareas.split() if t in NOMBRE_TAREA]
    cabecera = (f"Orden de trabajo {ot} del {fecha}. Equipo {equipo} ({NOMBRE_EQUIPO.get(equipo, equipo)}). "
                f"Tarea {tareas} ({', '.join(nombres) or 'sin nombre'}). Ejecutor: {ejecutor}.")
    return cabecera + "\n" + expandir_abreviaturas(texto[m.end():].strip())


def ruta_documentos() -> Path:
    """`DOCUMENTOS_PATH` si está definida; si no, `datos/documentos` del repo o `/app/datos/documentos` en la imagen."""
    if os.environ.get("DOCUMENTOS_PATH"):
        return Path(os.environ["DOCUMENTOS_PATH"])
    return next((r for r in RUTAS_POR_DEFECTO if (r / "fragmentos.jsonl").exists()), RUTAS_POR_DEFECTO[0])


@dataclass(frozen=True)
class FragmentoCorpus:
    """Una sección de un documento o una orden del historial, con todo lo que se indexa en Postgres."""

    cita: str
    documento: str
    seccion: str
    titulo: str
    texto: str
    vigente: bool
    aplica_pia3: bool
    tipo_documento: str
    titulo_documento: str
    revision: str | None = None
    fabricante: str | None = None
    equipos: tuple[str, ...] = ()
    pagina: int | None = None
    clave: str | None = None
    motivo_no_aplica: str | None = None
    fecha: date | None = None

    @property
    def texto_busqueda(self) -> str:
        """Lo que se indexa para buscar (el `tsvector` y el embedding). Solo cambia en las órdenes."""
        return texto_busqueda_orden(self.texto) if self.tipo_documento == TIPO_HISTORIAL else self.texto

    def texto_para_embeber(self) -> str:
        """El texto con una línea que dice de qué documento y revisión es (chunking contextual)."""
        if self.tipo_documento == TIPO_HISTORIAL:
            return f"Historial de PIA-3. {self.texto_busqueda}"
        rev = f", revisión {self.revision}" if self.revision else ""
        return f"{self.titulo_documento} ({self.documento}{rev}). {self.texto}"


@dataclass
class Corpus:
    fragmentos: list[FragmentoCorpus]
    documentos: dict[str, dict] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.fragmentos)

    def por_cita(self) -> dict[str, FragmentoCorpus]:
        return {f.cita: f for f in self.fragmentos}

    def huella(self) -> str:
        """Hash de lo que se embebe: si cambia el corpus o el armado del texto, los embeddings precalculados vencen."""
        h = hashlib.sha256()
        for f in self.fragmentos:
            h.update(f.cita.encode())
            h.update(b"\0")
            h.update(f.texto_para_embeber().encode())
            h.update(b"\0")
        return h.hexdigest()[:16]


def motivo_no_aplica(clave: str | None, clave_capitulo: str | None) -> str | None:
    """Por qué una sección no aplica a PIA-3 (por su clave o la de su capítulo), o None si aplica."""
    return NO_APLICA_POR_CLAVE.get(clave or "") or NO_APLICA_POR_CLAVE.get(clave_capitulo or "")


def _capitulo(numero: str) -> str:
    return numero.split(".")[0]


def _fragmento_orden(linea: dict) -> FragmentoCorpus:
    m = _CABECERA_ORDEN.match(linea["texto"])
    equipo, fecha = (m.group(3), date.fromisoformat(m.group(2))) if m else (None, None)
    return FragmentoCorpus(
        cita=linea["id"], documento=TIPO_HISTORIAL, seccion=linea["numero"], titulo=linea["titulo"],
        texto=linea["texto"], vigente=bool(linea.get("vigente", True)), aplica_pia3=True,
        tipo_documento=TIPO_HISTORIAL, titulo_documento="Historial de órdenes de trabajo de PIA-3",
        equipos=(equipo,) if equipo else (), fecha=fecha)


def armar_fragmentos(lineas: list[dict], indice: dict) -> list[FragmentoCorpus]:
    """Une cada línea de `fragmentos.jsonl` con los metadatos de su documento y decide si aplica a PIA-3."""
    docs = {d["id"]: d for d in indice.get("documentos", [])}
    claves = {(l["doc"], l["numero"]): l.get("clave") for l in lineas}
    salida = []
    for l in lineas:
        if l["doc"] == TIPO_HISTORIAL:
            salida.append(_fragmento_orden(l))
            continue
        d = docs.get(l["doc"], {})
        motivo = motivo_no_aplica(l.get("clave"), claves.get((l["doc"], _capitulo(l["numero"]))))
        salida.append(FragmentoCorpus(
            cita=l["id"], documento=l["doc"], seccion=l["numero"], titulo=l["titulo"], texto=l["texto"],
            vigente=bool(l.get("vigente", d.get("vigente", True))), aplica_pia3=motivo is None,
            motivo_no_aplica=motivo, tipo_documento=d.get("tipo", "documento"),
            titulo_documento=d.get("titulo", l["doc"]), revision=d.get("revision"), fabricante=d.get("emisor"),
            equipos=tuple(d.get("equipos", [])), pagina=l.get("pagina"), clave=l.get("clave")))
    return salida


def cargar_corpus(base: Path | None = None) -> Corpus:
    base = base or ruta_documentos()
    lineas = [json.loads(x) for x in (base / "fragmentos.jsonl").read_text(encoding="utf-8").splitlines() if x]
    indice = json.loads((base / "indice.json").read_text(encoding="utf-8"))
    return Corpus(armar_fragmentos(lineas, indice), {d["id"]: d for d in indice.get("documentos", [])})
