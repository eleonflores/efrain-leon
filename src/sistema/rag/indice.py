"""Esquema del RAG en PostgreSQL 16 + pgvector y su carga al arrancar.

Una sola tabla, `rag_fragmentos`: el texto de cada sección u orden, su vector, un `tsvector` en español generado por
Postgres y los metadatos para filtrar y citar (documento, revisión, fabricante, equipos, sección, título, cita,
página, vigente, si aplica a PIA-3). Vectores, texto y metadatos en la misma base: el filtro de vigencia y
aplicabilidad es un `WHERE` dentro de cada búsqueda, antes del top-k.

`rag_lexemas` guarda en cuántos fragmentos aparece cada lexema (`ts_stat`): con eso la lista léxica puntúa con BM25
en SQL (ver `busqueda.py`). `ts_rank` no tiene IDF y en este corpus "bomba" pesaría lo mismo que "cavitación".

**Carga.** El corrector borra los volúmenes entre escenarios, así que cada arranque puede encontrar la base vacía.
`asegurar_indice()` es idempotente: si `rag_meta` dice que lo cargado corresponde a este corpus y a este modelo, no
hace nada; si no, en una transacción con lock (el sistema y el servidor MCP pueden arrancar a la vez) recrea las
tablas, copia los fragmentos con los vectores precalculados en la imagen (`COPY`, 701 filas), calcula las
estadísticas léxicas y recién después crea los índices HNSW (coseno) y GIN (texto, códigos, equipos), como pide
pgvector. Tarda menos de un segundo.

Si faltan los vectores precalculados (o son de otro corpus) los calcula en el momento si el modelo está disponible;
si tampoco está el modelo, carga sin vectores y la búsqueda queda solo léxica (y lo dice).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np
import psycopg
from psycopg.rows import tuple_row

from sistema.rag.consulta import codigos_en
from sistema.rag.corpus import Corpus, FragmentoCorpus, cargar_corpus
from sistema.rag.embeddings import Embedder, ModeloEmbeddings, leer_vectores, modelo_configurado

log = logging.getLogger(__name__)

VERSION_ESQUEMA = "5"
CONFIG_TEXTO = "es_planta"
LLAVE_LOCK = 0x52414731  # "RAG1": serializa la carga entre procesos

COLUMNAS = ("cita", "documento", "revision", "tipo_documento", "titulo_documento", "fabricante", "equipos", "seccion",
            "titulo", "pagina", "fecha", "vigente", "aplica_pia3", "motivo_no_aplica", "codigos", "codigos_titulo",
            "texto", "texto_busqueda", "embedding")


# Español de Postgres sin tildes: el historial está escrito sin tildes ("cigueñal", "valvulas", "succion") y la
# configuración `spanish` sola no une "cigüeñal" con "ciguenal".
CONFIG_SQL = f"""
CREATE EXTENSION IF NOT EXISTS unaccent;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = '{CONFIG_TEXTO}') THEN
        CREATE TEXT SEARCH CONFIGURATION {CONFIG_TEXTO} (COPY = spanish);
        ALTER TEXT SEARCH CONFIGURATION {CONFIG_TEXTO}
            ALTER MAPPING FOR hword, hword_part, word WITH unaccent, spanish_stem;
    END IF;
END $$;
"""


def ddl(dim: int) -> str:
    return f"""
CREATE TABLE rag_fragmentos (
    cita             text PRIMARY KEY,
    documento        text NOT NULL,
    revision         text,
    tipo_documento   text NOT NULL,
    titulo_documento text NOT NULL,
    fabricante       text,
    equipos          text[] NOT NULL DEFAULT '{{}}',
    seccion          text NOT NULL,
    titulo           text NOT NULL,
    pagina           int,
    fecha            date,
    vigente          boolean NOT NULL,
    aplica_pia3      boolean NOT NULL,
    motivo_no_aplica text,
    codigos          text[] NOT NULL DEFAULT '{{}}',
    codigos_titulo   text[] NOT NULL DEFAULT '{{}}',
    texto            text NOT NULL,
    texto_busqueda   text NOT NULL,
    tsv              tsvector GENERATED ALWAYS AS (to_tsvector('{CONFIG_TEXTO}', texto_busqueda)) STORED,
    largo            int NOT NULL DEFAULT 0,
    embedding        vector({dim})
);
CREATE TABLE rag_lexemas (lexema text PRIMARY KEY, df int NOT NULL);
"""


INDICES = """
CREATE INDEX rag_fragmentos_hnsw ON rag_fragmentos USING hnsw (embedding vector_cosine_ops);
CREATE INDEX rag_fragmentos_tsv ON rag_fragmentos USING gin (tsv);
CREATE INDEX rag_fragmentos_codigos ON rag_fragmentos USING gin (codigos);
CREATE INDEX rag_fragmentos_equipos ON rag_fragmentos USING gin (equipos);
"""


@dataclass(frozen=True)
class EstadoIndice:
    cargado: bool
    fragmentos: int
    con_vectores: bool
    version: str
    segundos: float

    def __str__(self) -> str:
        accion = f"cargado en {self.segundos:.2f} s" if self.cargado else "ya estaba al día"
        modo = "con vectores" if self.con_vectores else "SIN vectores (búsqueda solo léxica)"
        return f"Índice RAG {accion}: {self.fragmentos} fragmentos, {modo} ({self.version})"


def version_indice(modelo: ModeloEmbeddings, huella: str, con_vectores: bool) -> str:
    return f"v{VERSION_ESQUEMA}|{modelo.clave if con_vectores else 'sin-vectores'}|{huella}"


def _vector_texto(v: np.ndarray | None) -> str | None:
    return None if v is None else "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def fila(f: FragmentoCorpus, vector: np.ndarray | None) -> tuple:
    """La fila que se copia a `rag_fragmentos` (en el orden de `COLUMNAS`)."""
    return (f.cita, f.documento, f.revision, f.tipo_documento, f.titulo_documento, f.fabricante, list(f.equipos),
            f.seccion, f.titulo, f.pagina, f.fecha, f.vigente, f.aplica_pia3, f.motivo_no_aplica,
            codigos_en(f.texto), codigos_en(f.titulo), f.texto, f.texto_busqueda, _vector_texto(vector))


def vectores_para(corpus: Corpus, modelo: ModeloEmbeddings, embedder: Embedder | None = None
                  ) -> dict[str, np.ndarray] | None:
    """Los vectores precalculados si corresponden a este corpus; si no, los calcula; si no hay modelo, None."""
    precalculados = leer_vectores(modelo.archivo_vectores())
    if precalculados and precalculados.huella == corpus.huella() and precalculados.modelo == modelo.clave:
        return precalculados.por_cita()
    log.warning("No hay vectores precalculados de %s para este corpus (%s): se calculan ahora",
                modelo.clave, modelo.archivo_vectores())
    try:
        embedder = embedder or Embedder(modelo)
        return dict(zip([f.cita for f in corpus.fragmentos],
                        embedder.pasajes([f.texto_para_embeber() for f in corpus.fragmentos])))
    except Exception:
        log.exception("No se pudo cargar el modelo de embeddings: el índice queda sin vectores")
        return None


async def _version_cargada(cur: psycopg.AsyncCursor) -> str | None:
    await cur.execute("SELECT to_regclass('rag_meta') IS NOT NULL AND to_regclass('rag_fragmentos') IS NOT NULL")
    if not (await cur.fetchone())[0]:
        return None
    await cur.execute("SELECT valor FROM rag_meta WHERE clave = 'version'")
    r = await cur.fetchone()
    return r[0] if r else None


async def _cargar(cur: psycopg.AsyncCursor, corpus: Corpus, vectores: dict[str, np.ndarray] | None, dim: int,
                  version: str) -> None:
    await cur.execute("DROP TABLE IF EXISTS rag_fragmentos, rag_lexemas")
    await cur.execute(CONFIG_SQL)
    await cur.execute(ddl(dim))
    async with cur.copy(f"COPY rag_fragmentos ({', '.join(COLUMNAS)}) FROM STDIN") as copia:
        for f in corpus.fragmentos:
            await copia.write_row(fila(f, (vectores or {}).get(f.cita)))
    await cur.execute("""UPDATE rag_fragmentos f SET largo = s.largo
                         FROM (SELECT cita, coalesce(sum(coalesce(array_length(u.positions, 1), 1)), 0) AS largo
                               FROM rag_fragmentos, unnest(tsv) u GROUP BY cita) s
                         WHERE s.cita = f.cita""")
    await cur.execute("INSERT INTO rag_lexemas SELECT word, ndoc FROM ts_stat('SELECT tsv FROM rag_fragmentos')")
    await cur.execute(INDICES)
    await cur.execute("INSERT INTO rag_meta (clave, valor) VALUES ('version', %s) "
                      "ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor", (version,))


async def asegurar_indice(conexion: psycopg.AsyncConnection | str, *, modelo: ModeloEmbeddings | None = None,
                          corpus: Corpus | None = None, forzar: bool = False,
                          embedder: Embedder | None = None) -> EstadoIndice:
    """Deja `rag_fragmentos` cargado con este corpus y este modelo. Idempotente; seguro con varios procesos.

    Recibe una conexión abierta (la del sistema, `autocommit=True`) o una URL de Postgres.
    """
    if isinstance(conexion, str):
        async with await psycopg.AsyncConnection.connect(conexion, autocommit=True) as con:
            return await asegurar_indice(con, modelo=modelo, corpus=corpus, forzar=forzar, embedder=embedder)
    t0 = time.perf_counter()
    modelo = modelo or modelo_configurado()
    corpus = corpus or cargar_corpus()
    async with conexion.cursor(row_factory=tuple_row) as cur:
        await cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await cur.execute("CREATE TABLE IF NOT EXISTS rag_meta (clave text PRIMARY KEY, valor text NOT NULL)")
        huella = corpus.huella()
        if not forzar and (await _version_cargada(cur)) == version_indice(modelo, huella, True):
            await cur.execute("SELECT count(*) FROM rag_fragmentos")
            return EstadoIndice(False, (await cur.fetchone())[0], True, version_indice(modelo, huella, True),
                                time.perf_counter() - t0)
    vectores = vectores_para(corpus, modelo, embedder)
    version = version_indice(modelo, huella, vectores is not None)
    async with conexion.transaction(), conexion.cursor(row_factory=tuple_row) as cur:
        await cur.execute("SELECT pg_advisory_xact_lock(%s)", (LLAVE_LOCK,))
        if forzar or (await _version_cargada(cur)) != version:
            await _cargar(cur, corpus, vectores, modelo.dim, version)
            cargado = True
        else:
            cargado = False  # otro proceso lo cargó mientras esperábamos el lock
    if cargado:
        async with conexion.cursor() as cur:
            await cur.execute("ANALYZE rag_fragmentos")
        log.info("Índice RAG cargado: %d fragmentos (%s)", len(corpus), version)
    return EstadoIndice(cargado, len(corpus), vectores is not None, version, time.perf_counter() - t0)
