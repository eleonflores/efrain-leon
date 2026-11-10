"""Búsqueda híbrida en los manuales y el historial: semántica + BM25 en Postgres + códigos exactos."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import psycopg
from psycopg.rows import dict_row

from sistema.rag.consulta import Consulta, preparar
from sistema.rag.embeddings import Embedder
from sistema.rag.indice import CONFIG_TEXTO

log = logging.getLogger(__name__)

LISTAS = ("sem", "lex", "cod")
FUSION = "cc"
PESOS_CC = {"sem": 0.4, "lex": 0.6, "cod": 0.2}
RRF_K = 60
CANDIDATOS = 50          # por lista, antes de fusionar
MAX_FRAGMENTOS_CODIGO = 15   # un código que aparece en más fragmentos no entra en la lista de códigos
BM25_K1, BM25_B = 1.2, 0.75
LARGO_TEXTO = 700


@dataclass(frozen=True)
class Candidato:
    """Un resultado de una de las listas: su posición (los empates comparten posición) y su puntaje en esa lista."""

    cita: str
    posicion: int
    valor: float = 0.0


class ErrorRag(Exception):
    """La base del RAG no está disponible (Postgres caído o sin cargar). Es transitorio."""


@dataclass(frozen=True)
class Filtros:
    """Filtros que se aplican antes del top-k. Por defecto: solo lo vigente y lo que aplica a PIA-3."""

    documentos: tuple[str, ...] = ()
    equipo: str | None = None
    tipos_documento: tuple[str, ...] = ()
    incluir_no_vigentes: bool = False
    incluir_no_aplicables: bool = False


@dataclass(frozen=True)
class Fragmento:
    cita: str
    documento: str
    revision: str | None
    seccion: str
    titulo: str
    pagina: int | None
    fabricante: str | None
    equipos: tuple[str, ...]
    vigente: bool
    texto: str
    puntaje: float
    listas: tuple[str, ...] = field(default=())


def condiciones(filtros: Filtros) -> tuple[str, dict]:
    """El `WHERE` del filtro previo (el mismo en las tres listas) y sus parámetros."""
    partes, params = [], {}
    if not filtros.incluir_no_vigentes:
        partes.append("vigente")
    if not filtros.incluir_no_aplicables:
        partes.append("aplica_pia3")
    if filtros.documentos:
        partes.append("documento = ANY(%(f_documentos)s)")
        params["f_documentos"] = list(filtros.documentos)
    if filtros.tipos_documento:
        partes.append("tipo_documento = ANY(%(f_tipos)s)")
        params["f_tipos"] = list(filtros.tipos_documento)
    if filtros.equipo:
        # Las órdenes generales (equipo PLANTA) cuentan para todos.
        partes.append("(%(f_equipo)s = ANY(equipos) OR 'PLANTA' = ANY(equipos))")
        params["f_equipo"] = filtros.equipo
    return (" AND ".join(partes) or "true"), params


def _posiciones(lista: Sequence[str | Candidato]) -> list[tuple[str, int]]:
    """Citas en orden → posiciones 1, 2, 3…; `Candidato` → su propia posición."""
    vistos, salida = set(), []
    for x in lista:
        cita, pos = (x, len(salida) + 1) if isinstance(x, str) else (x.cita, x.posicion)
        if cita not in vistos:
            vistos.add(cita)
            salida.append((cita, pos))
    return salida


def fusionar_rrf(listas: dict[str, Sequence[str | Candidato]], *, k: int = RRF_K,
                 pesos: dict[str, float] | None = None) -> list[tuple[str, float, tuple[str, ...]]]:
    """Reciprocal Rank Fusion: `Σ peso / (k + posición)`; devuelve `(cita, puntaje, listas)` de mayor a menor."""
    puntaje: dict[str, float] = {}
    mejor: dict[str, int] = {}
    fuentes: dict[str, list[str]] = {}
    for nombre, lista in listas.items():
        peso = (pesos or {}).get(nombre, 1.0)
        for cita, pos in _posiciones(lista):
            puntaje[cita] = puntaje.get(cita, 0.0) + peso / (k + pos)
            mejor[cita] = min(mejor.get(cita, pos), pos)
            fuentes.setdefault(cita, []).append(nombre)
    orden = sorted(puntaje, key=lambda c: (-puntaje[c], mejor[c], c))
    return [(c, puntaje[c], tuple(fuentes[c])) for c in orden]


def fusionar_cc(listas: dict[str, Sequence[Candidato]], *, pesos: dict[str, float] | None = None
                ) -> list[tuple[str, float, tuple[str, ...]]]:
    """Combinación convexa de las listas normalizadas min-max; devuelve `(cita, puntaje, listas)` de mayor a menor."""
    pesos = PESOS_CC if pesos is None else pesos
    total: dict[str, float] = {}
    mejor: dict[str, int] = {}
    fuentes: dict[str, list[str]] = {}
    for nombre, lista in listas.items():
        if not lista:
            continue
        valores = [c.valor for c in lista]
        bajo, alto = min(valores), max(valores)
        for c in lista:
            if nombre in fuentes.get(c.cita, ()):
                continue
            normal = (c.valor - bajo) / (alto - bajo) if alto > bajo else 1.0
            total[c.cita] = total.get(c.cita, 0.0) + pesos.get(nombre, 0.0) * normal
            mejor[c.cita] = min(mejor.get(c.cita, c.posicion), c.posicion)
            fuentes.setdefault(c.cita, []).append(nombre)
    orden = sorted(total, key=lambda c: (-total[c], mejor[c], c))
    return [(c, total[c], tuple(fuentes[c])) for c in orden]


def recortar(texto: str, largo: int = LARGO_TEXTO) -> str:
    """Corta en el último espacio antes de `largo` y marca el corte con '…'."""
    if len(texto) <= largo:
        return texto
    corte = texto.rfind(" ", 0, largo)
    return texto[: corte if corte > largo // 2 else largo].rstrip(" ,;:") + " …"


def sql_listas(listas: Iterable[str], where: str) -> str:
    """Una consulta que devuelve `(lista, cita, posicion)` de cada lista pedida."""
    partes = []
    if "sem" in listas:
        partes.append(f"""
    (SELECT 'sem' AS lista, cita, row_number() OVER (ORDER BY distancia, cita) AS posicion, 1 - distancia AS valor FROM (
        SELECT cita, embedding <=> %(vector)s::vector AS distancia
        FROM rag_fragmentos WHERE {where} AND embedding IS NOT NULL
        ORDER BY embedding <=> %(vector)s::vector LIMIT %(n)s) sem)""")
    if "lex" in listas:
        partes.append(f"""
    (SELECT 'lex' AS lista, cita, row_number() OVER (ORDER BY valor DESC, cita) AS posicion, valor FROM (
        SELECT f.cita, sum(qi.idf * u.tf * ({BM25_K1} + 1)
                           / (u.tf + {BM25_K1} * (1 - {BM25_B} + {BM25_B} * f.largo / est.prom))) AS valor
        FROM rag_fragmentos f
        CROSS JOIN est
        CROSS JOIN LATERAL (SELECT lexeme, coalesce(array_length(positions, 1), 1) AS tf FROM unnest(f.tsv)) u
        JOIN qi ON qi.lex = u.lexeme
        WHERE f.tsv @@ (SELECT tsq FROM consulta_lex) AND {where}
        GROUP BY f.cita ORDER BY valor DESC, f.cita LIMIT %(n)s) lex)""")
    if "cod" in listas:
        partes.append(f"""
    (SELECT 'cod' AS lista, cita, rank() OVER (ORDER BY valor DESC) AS posicion, valor FROM (
        SELECT f.cita, sum(ln(est.total / dc.df) * CASE WHEN c = ANY(f.codigos_titulo) THEN 2 ELSE 1 END) AS valor
        FROM rag_fragmentos f
        CROSS JOIN est
        CROSS JOIN LATERAL unnest(f.codigos) c
        JOIN df_codigos dc ON dc.codigo = c
        WHERE f.codigos && %(codigos)s::text[] AND {where}
        GROUP BY f.cita ORDER BY valor DESC, f.cita LIMIT %(n)s) cod)""")
    ctes = f"""
WITH est AS (SELECT count(*)::float AS total, greatest(avg(largo), 1)::float AS prom FROM rag_fragmentos),
consulta_lex AS (SELECT replace(plainto_tsquery('{CONFIG_TEXTO}', %(texto)s)::text, ' & ', ' | ')::tsquery AS tsq),
qi AS (
    SELECT l.lexema AS lex, ln(1 + (est.total - l.df + 0.5) / (l.df + 0.5)) AS idf
    FROM (SELECT DISTINCT lexeme FROM unnest(to_tsvector('{CONFIG_TEXTO}', %(texto)s))) q
    JOIN rag_lexemas l ON l.lexema = q.lexeme CROSS JOIN est),
df_codigos AS (
    SELECT c AS codigo, count(*) AS df FROM rag_fragmentos, unnest(codigos) c
    WHERE codigos && %(codigos)s::text[] AND c = ANY(%(codigos)s::text[]) GROUP BY c
    HAVING count(*) <= %(max_df)s)"""
    return ctes + "\n" + "\nUNION ALL".join(partes)


class BuscadorManuales:
    """Conecta y carga el modelo en la primera consulta; sin modelo de embeddings sigue con las listas léxicas."""

    def __init__(self, url: str | None = None, *, embedder: Embedder | None = None, listas: Sequence[str] = LISTAS,
                 fusion: str = FUSION, pesos: dict[str, float] | None = None, rrf_k: int = RRF_K,
                 candidatos: int = CANDIDATOS, expandir_codigos: bool = True, expandir_equipos: bool = True,
                 asegurar: bool = True):
        self.url = url
        self.embedder = embedder
        self.listas = tuple(listas)
        self.pesos = pesos
        self.fusion = fusion
        self.rrf_k, self.candidatos = rrf_k, candidatos
        self.expandir_codigos, self.expandir_equipos = expandir_codigos, expandir_equipos
        self.asegurar = asegurar
        self._con: psycopg.AsyncConnection | None = None
        self._lock = asyncio.Lock()
        self._sin_modelo = False

    @property
    def modo(self) -> str:
        return "hibrida" if "sem" in self._listas_activas() and len(self._listas_activas()) > 1 else (
            "vectores" if "sem" in self._listas_activas() else "lexica")

    def _listas_activas(self) -> tuple[str, ...]:
        return tuple(x for x in self.listas if not (x == "sem" and self._sin_modelo))

    def _embedder(self) -> Embedder:
        if self.embedder is None:
            self.embedder = Embedder()
        return self.embedder

    async def _conexion(self) -> psycopg.AsyncConnection:
        if self._con is not None and not self._con.closed:
            return self._con
        if self.url is None:
            from sistema.config import CONFIG
            self.url = CONFIG.database_url
        try:
            con = await psycopg.AsyncConnection.connect(self.url, autocommit=True, row_factory=dict_row,
                                                        connect_timeout=5)
            if self.asegurar:
                from sistema.rag.indice import asegurar_indice
                estado = await asegurar_indice(con, modelo=self._embedder().modelo, embedder=self.embedder)
                log.info("%s", estado)
            await con.execute("SET hnsw.iterative_scan = strict_order")
            await con.execute("SET hnsw.ef_search = 100")
        except psycopg.Error as e:
            raise ErrorRag(f"La base del RAG no está disponible: {str(e).splitlines()[0] if str(e) else e}") from e
        self._con = con
        return con

    async def _vector(self, texto: str) -> str | None:
        if "sem" not in self._listas_activas():
            return None
        try:
            v = await asyncio.to_thread(self._embedder().consulta, texto)
        except Exception:
            log.exception("No se pudo usar el modelo de embeddings: sigo solo con la búsqueda léxica")
            self._sin_modelo = True
            return None
        return "[" + ",".join(f"{x:.7g}" for x in v) + "]"

    async def candidatos_por_lista(self, consulta: Consulta, filtros: Filtros) -> dict[str, list[Candidato]]:
        vector = await self._vector(consulta.pregunta)
        listas = [x for x in self._listas_activas() if x != "sem" or vector is not None]
        if not listas:
            return {}
        where, params = condiciones(filtros)
        params |= {"vector": vector, "texto": consulta.texto_lexico, "codigos": list(consulta.codigos),
                   "n": self.candidatos, "max_df": MAX_FRAGMENTOS_CODIGO}
        async with self._lock:
            con = await self._conexion()
            try:
                cur = await con.execute(sql_listas(listas, where), params)
                filas = await cur.fetchall()
            except psycopg.OperationalError as e:
                await con.close()
                raise ErrorRag(f"Se cortó la conexión con la base del RAG: {e}") from e
        salida: dict[str, list[Candidato]] = {x: [] for x in listas}
        for f in sorted(filas, key=lambda f: (f["lista"], f["posicion"], f["cita"])):
            salida[f["lista"]].append(Candidato(f["cita"], f["posicion"], float(f["valor"])))
        return salida

    def fusionar(self, listas: dict[str, list[Candidato]]) -> list[tuple[str, float, tuple[str, ...]]]:
        if self.fusion == "rrf":
            return fusionar_rrf(listas, k=self.rrf_k, pesos=self.pesos)
        return fusionar_cc(listas, pesos=self.pesos)

    async def buscar(self, pregunta: str, k: int = 5, filtros: Filtros | None = None) -> list[Fragmento]:
        """Los k fragmentos más relevantes para la pregunta, ya filtrados por vigencia y aplicabilidad."""
        filtros = filtros or Filtros()
        consulta = preparar(pregunta, expandir_codigos=self.expandir_codigos, expandir_equipos=self.expandir_equipos)
        fusion = self.fusionar(await self.candidatos_por_lista(consulta, filtros))[:k]
        if not fusion:
            return []
        async with self._lock:
            cur = await self._con.execute(
                "SELECT cita, documento, revision, seccion, titulo, pagina, fabricante, equipos, vigente, texto "
                "FROM rag_fragmentos WHERE cita = ANY(%s)", ([c for c, _, _ in fusion],))
            datos = {f["cita"]: f for f in await cur.fetchall()}
        return [Fragmento(cita=c, documento=d["documento"], revision=d["revision"], seccion=d["seccion"],
                          titulo=d["titulo"], pagina=d["pagina"], fabricante=d["fabricante"],
                          equipos=tuple(d["equipos"] or ()), vigente=d["vigente"], texto=recortar(d["texto"]),
                          puntaje=round(p, 5), listas=fuentes)
                for c, p, fuentes in fusion if (d := datos.get(c))]

    async def citas(self, pregunta: str, k: int = 20, filtros: Filtros | None = None) -> list[str]:
        """Solo las citas, en orden."""
        consulta = preparar(pregunta, expandir_codigos=self.expandir_codigos, expandir_equipos=self.expandir_equipos)
        fusion = self.fusionar(await self.candidatos_por_lista(consulta, filtros or Filtros()))
        return [c for c, _, _ in fusion[:k]]

    async def cerrar(self) -> None:
        if self._con is not None:
            await self._con.close()
            self._con = None
