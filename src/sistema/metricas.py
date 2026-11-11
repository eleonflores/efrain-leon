"""Métricas del sistema: el consumo por modelo que muestra el visor y el reporte de funcionamiento.

    python -m sistema.metricas          # reporte leído de $DATABASE_URL
    docker compose exec sistema python -m sistema.metricas
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from sistema.config import CONFIG
from sistema.persistencia.db import Base
from sistema.rag.indexar import correr


def _velocidad(salida: int, ms: int) -> float | None:
    return round(salida / (ms / 1000), 2) if salida and ms else None


def consumo_tokens(filas: list[dict], cargados: list[str], sistema: str, ts: datetime) -> dict:
    """`ConsumoTokens` del visor: los modelos cargados primero, aunque no tengan tokens, y después los de la base."""
    por_modelo = {f["modelo"]: f for f in filas}
    orden = cargados + [m for m in por_modelo if m not in cargados]
    vacio = {"entrada": 0, "salida": 0, "generacion_ms": 0, "estimado_ms": 0}
    usados = [(m, por_modelo.get(m, vacio)) for m in orden]
    modelos = [{"modelo": m, "tokens_entrada": f["entrada"], "tokens_salida": f["salida"],
                "tokens_total": f["entrada"] + f["salida"],
                "tokens_por_segundo": _velocidad(f["salida"], f["generacion_ms"] + f["estimado_ms"]),
                "velocidad_estimada": f["estimado_ms"] > 0} for m, f in usados]
    entrada, salida = sum(f["entrada"] for _, f in usados), sum(f["salida"] for _, f in usados)
    ms = sum(f["generacion_ms"] + f["estimado_ms"] for _, f in usados)
    return {"ts": ts.isoformat(), "sistema": sistema, "tokens_entrada": entrada, "tokens_salida": salida,
            "tokens_total": entrada + salida, "tokens_por_segundo": _velocidad(salida, ms),
            "velocidad_estimada": any(f["estimado_ms"] for _, f in usados), "modelos": modelos}


def _num(x: float | None, decimales: int = 1, unidad: str = " s") -> str:
    if x is None:
        return "—"
    return f"{x:,.{decimales}f}".replace(",", "_").replace(".", ",").replace("_", ".") + unidad


def _pct(a: int, b: int) -> str:
    return _num(100 * a / b, 1, " %") if b else "—"


def _paso(p: dict, consumo: dict[str, dict]) -> str:
    duracion = f"p50 {_num(p['p50_ms'] / 1000)} / p95 {_num(p['p95_ms'] / 1000)}"
    if p["etapa"] == "transcripcion":
        c = consumo.get(p["nombre"], {})
        velocidad = _velocidad(c.get("salida", 0), c.get("generacion_ms", 0) + c.get("estimado_ms", 0))
        return (f"{p['n']} notas · audio p50 {_num(p['audio_p50_s'])} → transcribe en {duracion} "
                f"({_num(p['ms'] / 1000 / p['audio_s'], 2, '×') if p['audio_s'] else '—'} el audio) · "
                f"{_num(c.get('salida', 0), 0, ' tokens')} a {_num(velocidad, 1, ' tok/s')}")
    if p["etapa"] == "extraccion_reglas":
        completas = p["n"] - p["fallas"]
        p50 = "< 1 ms" if p["p50_ms"] < 1 else _num(p["p50_ms"], 0, " ms")
        return f"{p['n']} notas · {completas} completas ({_pct(completas, p['n'])}) · p50 {p50}"
    c = consumo.get(p["nombre"])
    texto = f"{p['n']} llamadas · {p['fallas']} fallas ({p['timeouts']} por timeout) · {duracion}"
    if c:
        velocidad = _velocidad(c["salida"], c["generacion_ms"] + c["estimado_ms"])
        texto += (f" · {_num(c['entrada'], 0, '')} + {_num(c['salida'], 0, '')} tokens "
                  f"a {_num(velocidad, 1, ' tok/s')}")
    return texto


def reporte(e: dict, sistema: str) -> str:
    total = sum(n["n"] for n in e["notas"])
    fases = ", ".join(f"{n['fase']} {n['n']}" for n in e["notas"])
    lineas = [f"Sistema {sistema} · {total} notas ({fases}) · costo USD 0, todo local", "", "Fluidez, en tiempo real"]
    for rotulo, d, cuales in (("Nota → primer mensaje en la tablet", e["a_la_tablet"], "notas"),
                              ("Nota → alerta de seguridad", e["a_la_alerta"], "alertas (límite 30 s)")):
        if d["n"]:
            lineas.append(f"  {rotulo:<36} p50 {_num(d['p50'])} · p95 {_num(d['p95'])} · máx {_num(d['max'])} · "
                          f"{cuales}: {d['n']}")
    consumo = {c["modelo"]: c for c in e["consumo"]}
    lineas += ["", "Modelos y reglas"]
    lineas += [f"  {p['nombre']:<28} {_paso(p, consumo)}" for p in e["pasos"]]
    d, cola = e["dialogo"], e["cola"]
    lineas += ["", "Diálogo con el operador",
               f"  Confirmadas al primer borrador {d['al_primero']} de {d['confirmadas']} "
               f"({_pct(d['al_primero'], d['confirmadas'])}) · preguntas {d['preguntas']} · "
               f"borradores rehechos {d['rehechos']}"]
    if e["abandonos"]:
        lineas.append("  Abandonadas: " + ", ".join(f"{a['n']} por {a['motivo']}" for a in e["abandonos"]))
    lineas += ["", f"Cola hacia la nube: {cola['enviados']} enviados · {cola['pendientes']} pendientes"]
    return "\n".join(lineas)


async def _leer(url: str) -> dict:
    db = Base(url)
    await db.conectar(intentos=1)
    return await db.estadisticas()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=None, help="por defecto $DATABASE_URL")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    print(reporte(correr(_leer(a.url or CONFIG.database_url)), CONFIG.sistema))


if __name__ == "__main__":
    main()
