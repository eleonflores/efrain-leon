from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger(__name__)

ESQUEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS notas (
    id            text PRIMARY KEY,
    recorrida_id  text,
    ts            timestamptz,
    operador      text,
    audio_url     text,
    fotos         jsonb NOT NULL DEFAULT '[]',
    transcripcion text,
    fase          text NOT NULL,
    intento       int  NOT NULL DEFAULT 0,
    borrador      jsonb,
    seguridad     jsonb,
    creada        timestamptz NOT NULL DEFAULT now(),
    actualizada   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS mensajes_tablet (
    id        text PRIMARY KEY,
    nota_id   text NOT NULL,
    payload   jsonb NOT NULL,
    respuesta jsonb,
    enviado   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mensajes_tablet_nota ON mensajes_tablet (nota_id);
CREATE TABLE IF NOT EXISTS partes (
    nota_id    text PRIMARY KEY,
    estado     text NOT NULL,
    filas      jsonb NOT NULL,
    ts         timestamptz,
    confirmado timestamptz
);
CREATE TABLE IF NOT EXISTS eventos (
    id       text PRIMARY KEY,
    payload  jsonb NOT NULL,
    contexto jsonb,
    creado   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS pasos (
    id             bigserial PRIMARY KEY,
    nota_id        text,
    etapa          text NOT NULL,
    modelo         text,
    herramienta    text,
    argumentos     jsonb,
    tokens_entrada int NOT NULL DEFAULT 0,
    tokens_salida  int NOT NULL DEFAULT 0,
    costo_usd      numeric NOT NULL DEFAULT 0,
    duracion_ms    int NOT NULL DEFAULT 0,
    ok             boolean NOT NULL DEFAULT true,
    detalle        jsonb,
    creado         timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS salida_nube (
    id      text PRIMARY KEY,
    orden   bigserial,
    tipo    text NOT NULL,
    payload jsonb NOT NULL,
    creado  timestamptz NOT NULL DEFAULT now(),
    enviado timestamptz
);
CREATE TABLE IF NOT EXISTS fotos (
    url       text PRIMARY KEY,
    tipo      text NOT NULL,
    contenido bytea NOT NULL,
    bajada    timestamptz NOT NULL DEFAULT now()
);
"""


def _j(valor) -> str:
    return json.dumps(valor, ensure_ascii=False, default=str)


class Base:
    def __init__(self, url: str):
        self.url = url
        self._con: psycopg.AsyncConnection | None = None
        self._lock = asyncio.Lock()

    async def conectar(self, intentos: int = 60) -> None:
        for i in range(intentos):
            try:
                self._con = await psycopg.AsyncConnection.connect(self.url, autocommit=True, row_factory=dict_row)
                await self._con.execute(ESQUEMA)
                log.info("Postgres listo")
                return
            except psycopg.OperationalError as e:
                if i == intentos - 1:
                    raise
                log.info("Esperando a Postgres (%s)", str(e).splitlines()[0])
                await asyncio.sleep(2)

    async def _exec(self, sql: str, params: tuple = ()) -> list[dict]:
        async with self._lock:
            assert self._con is not None, "Base sin conectar"
            cur = await self._con.execute(sql, params)
            return await cur.fetchall() if cur.description else []

    async def guardar_nota(self, nota: dict, fase: str) -> None:
        await self._exec(
            """INSERT INTO notas (id, recorrida_id, ts, operador, audio_url, fotos, fase)
               VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
            (nota["id"], nota.get("recorrida_id"), nota.get("ts"), nota.get("operador"), nota.get("audio_url"),
             _j(nota.get("fotos", [])), fase))

    async def actualizar_nota(self, nota_id: str, **campos) -> None:
        if not campos:
            return
        jsonb = {"borrador", "seguridad", "fotos"}
        sets = ", ".join(f"{k} = %s" for k in campos) + ", actualizada = now()"
        valores = tuple(_j(v) if k in jsonb else v for k, v in campos.items())
        await self._exec(f"UPDATE notas SET {sets} WHERE id = %s", (*valores, nota_id))

    async def nota(self, nota_id: str) -> dict | None:
        filas = await self._exec("SELECT * FROM notas WHERE id = %s", (nota_id,))
        return filas[0] if filas else None

    async def notas_abiertas(self) -> list[dict]:
        return await self._exec(
            "SELECT * FROM notas WHERE fase NOT IN ('confirmada', 'alerta', 'abandonada', 'sin_contenido') ORDER BY ts")

    async def guardar_foto(self, url: str, tipo: str, contenido: bytes) -> None:
        await self._exec("INSERT INTO fotos (url, tipo, contenido) VALUES (%s, %s, %s) ON CONFLICT (url) DO NOTHING",
                         (url, tipo, contenido))

    async def fotos_guardadas(self, urls: list[str]) -> dict[str, dict]:
        filas = await self._exec("SELECT url, tipo, contenido FROM fotos WHERE url = ANY(%s)", (urls,))
        return {f["url"]: f for f in filas}

    async def guardar_mensaje(self, nota_id: str, mensaje: dict) -> None:
        await self._exec("INSERT INTO mensajes_tablet (id, nota_id, payload) VALUES (%s, %s, %s) "
                         "ON CONFLICT (id) DO NOTHING", (mensaje["id"], nota_id, _j(mensaje)))

    async def guardar_respuesta(self, mensaje_id: str, respuesta: dict) -> str | None:
        filas = await self._exec("UPDATE mensajes_tablet SET respuesta = %s WHERE id = %s RETURNING nota_id",
                                 (_j(respuesta), mensaje_id))
        return filas[0]["nota_id"] if filas else None

    async def guardar_parte(self, nota_id: str, estado: str, filas: list[dict], ts) -> None:
        confirmado = datetime.now(timezone.utc) if estado == "Confirmado" else None
        await self._exec(
            """INSERT INTO partes (nota_id, estado, filas, ts, confirmado) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (nota_id) DO UPDATE SET estado = EXCLUDED.estado, filas = EXCLUDED.filas,
               confirmado = EXCLUDED.confirmado""",
            (nota_id, estado, _j(filas), ts, confirmado))

    async def guardar_evento(self, evento: dict, contexto: dict | None = None) -> bool:
        """True si el evento es nuevo."""
        filas = await self._exec("INSERT INTO eventos (id, payload, contexto) VALUES (%s, %s, %s) "
                                 "ON CONFLICT (id) DO NOTHING RETURNING id", (evento["id"], _j(evento), _j(contexto)))
        return bool(filas)

    async def registrar_paso(self, nota_id: str | None, etapa: str, *, modelo: str | None = None,
                             herramienta: str | None = None, argumentos: dict | None = None, tokens_entrada: int = 0,
                             tokens_salida: int = 0, costo_usd: float = 0.0, duracion_ms: int = 0, ok: bool = True,
                             detalle: dict | None = None) -> None:
        await self._exec(
            """INSERT INTO pasos (nota_id, etapa, modelo, herramienta, argumentos, tokens_entrada, tokens_salida,
               costo_usd, duracion_ms, ok, detalle) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (nota_id, etapa, modelo, herramienta, _j(argumentos), tokens_entrada, tokens_salida, costo_usd,
             duracion_ms, ok, _j(detalle)))

    async def consumo_por_modelo(self) -> list[dict]:
        """Tokens por modelo y el tiempo de las llamadas con salida: medido (`generacion_ms`) o estimado (duración)."""
        return await self._exec(
            """SELECT modelo, count(*)::int AS llamadas, sum(tokens_entrada)::int AS entrada,
                      sum(tokens_salida)::int AS salida,
                      coalesce(sum((detalle->>'generacion_ms')::int) FILTER (WHERE tokens_salida > 0), 0)::int
                          AS generacion_ms,
                      coalesce(sum(duracion_ms) FILTER (WHERE tokens_salida > 0 AND detalle->>'generacion_ms' IS NULL),
                               0)::int AS estimado_ms
               FROM pasos WHERE modelo IS NOT NULL GROUP BY modelo ORDER BY min(id)""")

    async def estadisticas(self) -> dict:
        """Lo que muestra `python -m sistema.metricas`."""
        demora = """SELECT count(*)::int AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY duracion_ms) / 1000 AS p50,
                           percentile_cont(0.95) WITHIN GROUP (ORDER BY duracion_ms) / 1000 AS p95,
                           max(duracion_ms) / 1000.0 AS max
                    FROM pasos WHERE etapa = 'primer_mensaje' AND argumentos->>'mensaje_id' ~ %s"""
        return {
            "notas": await self._exec("SELECT fase, count(*)::int AS n FROM notas GROUP BY fase ORDER BY n DESC"),
            "a_la_tablet": (await self._exec(demora, (".",)))[0],
            "a_la_alerta": (await self._exec(demora, ("-SEG$",)))[0],
            "pasos": await self._exec(
                """SELECT coalesce(modelo, herramienta) AS nombre, etapa, count(*)::int AS n,
                          count(*) FILTER (WHERE NOT ok)::int AS fallas,
                          count(*) FILTER (WHERE detalle->>'error' ~ '^TimeoutError')::int AS timeouts,
                          count(*) FILTER (WHERE jsonb_array_length(detalle->'condiciones') > 0)::int AS inseguras,
                          count(*) FILTER (WHERE detalle->>'tipo' = 'Escalado')::int AS escalados,
                          percentile_cont(0.5) WITHIN GROUP (ORDER BY duracion_ms) AS p50_ms,
                          percentile_cont(0.95) WITHIN GROUP (ORDER BY duracion_ms) AS p95_ms,
                          percentile_cont(0.5) WITHIN GROUP (ORDER BY (detalle->>'audio_s')::float) AS audio_p50_s,
                          sum((detalle->>'audio_s')::float) AS audio_s, sum(duracion_ms)::int AS ms
                   FROM pasos WHERE etapa NOT IN ('abandono', 'primer_mensaje') GROUP BY 1, 2 ORDER BY min(id)"""),
            "consumo": await self.consumo_por_modelo(),
            "abandonos": await self._exec("SELECT detalle->>'motivo' AS motivo, count(*)::int AS n FROM pasos "
                                          "WHERE etapa = 'abandono' GROUP BY 1 ORDER BY n DESC"),
            "dialogo": (await self._exec(
                """SELECT count(*) FILTER (WHERE n.fase = 'confirmada')::int AS confirmadas,
                          count(*) FILTER (WHERE n.fase = 'confirmada' AND m.borradores = 1)::int AS al_primero,
                          coalesce(sum(m.preguntas), 0)::int AS preguntas,
                          coalesce(sum(greatest(m.borradores - 1, 0)), 0)::int AS rehechos
                   FROM notas n LEFT JOIN (SELECT nota_id, count(*) FILTER (WHERE id ~ '-B[0-9]+$') AS borradores,
                                                  count(*) FILTER (WHERE id ~ '-P[0-9]+$') AS preguntas
                                           FROM mensajes_tablet GROUP BY nota_id) m ON m.nota_id = n.id"""))[0],
            "cola": (await self._exec("SELECT count(enviado)::int AS enviados, "
                                      "(count(*) - count(enviado))::int AS pendientes FROM salida_nube"))[0],
        }

    async def encolar(self, id_: str, tipo: str, payload: dict) -> None:
        await self._exec("INSERT INTO salida_nube (id, tipo, payload) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                         (id_, tipo, _j(payload)))

    async def pendientes(self, limite: int = 50) -> list[dict]:
        return await self._exec("SELECT id, tipo, payload FROM salida_nube WHERE enviado IS NULL ORDER BY orden "
                                "LIMIT %s", (limite,))

    async def cantidad_pendientes(self) -> int:
        return (await self._exec("SELECT count(*)::int AS n FROM salida_nube WHERE enviado IS NULL"))[0]["n"]

    async def marcar_enviado(self, id_: str) -> None:
        await self._exec("UPDATE salida_nube SET enviado = now() WHERE id = %s", (id_,))
