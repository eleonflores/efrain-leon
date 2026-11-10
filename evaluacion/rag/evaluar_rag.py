"""Evaluación del RAG contra la suite de Novit (71 preguntas) con su evaluador, `corpus.evaluar.evaluar`.

    # Postgres con pgvector (cualquiera; se carga solo):
    docker run -d --name rag-dev-db -e POSTGRES_USER=sistema -e POSTGRES_PASSWORD=sistema -e POSTGRES_DB=sistema \
        -p 5433:5432 pgvector/pgvector:0.8.1-pg16
    # Vectores precalculados de cada modelo candidato:
    python -m sistema.rag.indexar --precalcular --modelo e5-small-int8
    python -m sistema.rag.indexar --precalcular --modelo minilm-l12
    # Evaluación (BM25 de Novit, solo vectores, híbrida y ablaciones) → evaluacion/rag/resultados.json
    DATABASE_URL=postgresql://sistema:sistema@localhost:5433/sistema python evaluacion/rag/evaluar_rag.py

El evaluador se importa del repo de la planta (`$PLANTA_REPO`, por defecto `../academia2026-tp`): es el paquete
`corpus` de `planta/`. La suite y los fragmentos son las copias de `datos/documentos/` (idénticas a las de Novit).

Cada modelo candidato se mide además en un proceso aparte (`--medir-modelo`) con 2 hilos: tiempo de carga, RAM
(pico del proceso) y latencia de una consulta, que es lo único que el modelo hace en runtime.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "src"))
PLANTA = Path(os.environ.get("PLANTA_REPO", RAIZ.parent / "academia2026-tp")) / "planta"
sys.path.insert(0, str(PLANTA))

from corpus.evaluar import BM25, evaluar  # noqa: E402  (paquete del repo de la planta)

from sistema.rag.busqueda import BuscadorManuales, Filtros  # noqa: E402
from sistema.rag.corpus import cargar_corpus, ruta_documentos  # noqa: E402
from sistema.rag.embeddings import MODELO_POR_DEFECTO, MODELOS, Embedder  # noqa: E402
from sistema.rag.indexar import correr  # noqa: E402
from sistema.rag.indice import asegurar_indice  # noqa: E402

SALIDA = Path(__file__).parent / "resultados.json"
URL_DESARROLLO = "postgresql://sistema:sistema@localhost:5433/sistema"
KS = (1, 3, 5, 10)
HILOS = 2
TODO = Filtros(incluir_no_vigentes=True, incluir_no_aplicables=True)
NO_APLICAN = {f.cita for f in cargar_corpus().fragmentos if not f.aplica_pia3}

# nombre → (listas, filtros, opciones del buscador). "vectores" e "hibrida" son las configuraciones pedidas; el resto
# son ablaciones para ver qué aporta cada pieza. "hibrida" usa la fusión por defecto (combinación convexa).
SIN_EXPANSION = {"expandir_codigos": False, "expandir_equipos": False}
CONFIGS: dict[str, tuple[tuple[str, ...], Filtros, dict]] = {
    "vectores_sin_filtro": (("sem",), TODO, {}),
    "vectores": (("sem",), Filtros(), {}),
    "lexica": (("lex", "cod"), Filtros(), {}),
    "hibrida_rrf": (("sem", "lex", "cod"), Filtros(), {"fusion": "rrf"}),
    "hibrida_sin_filtro": (("sem", "lex", "cod"), TODO, {}),
    "hibrida_sin_codigos": (("sem", "lex"), Filtros(), {}),
    "hibrida_sin_expansion": (("sem", "lex", "cod"), Filtros(), SIN_EXPANSION),
    "hibrida": (("sem", "lex", "cod"), Filtros(), {}),
}
# Para los modelos que no se eligieron alcanza con lo pedido (la léxica no depende del modelo).
CONFIGS_COMPARACION = ("vectores_sin_filtro", "vectores", "hibrida_rrf", "hibrida")


def rev_c_antes_que_d(citas: list[str], k: int = 10) -> bool:
    """¿La primera sección del manual de la bomba en los primeros k es de la Rev. C (la vieja le gana a la vigente)?"""
    primera = next((c for c in citas[:k] if c.startswith(("TX350-C ", "TX350-D "))), None)
    return primera is not None and primera.startswith("TX350-C ")


def resumir(nombre: str, resultados: dict[str, list[str]], suite: list[dict], detalle: bool = False) -> dict:
    r = evaluar(lambda pregunta, k: resultados[pregunta][:k], suite, KS)
    salida = {"total": r["total"], "por_tipo": r["por_tipo"],
              "rev_c_antes_que_d@5": sum(rev_c_antes_que_d(resultados[q["pregunta"]], 5) for q in suite),
              "rev_c_antes_que_d@10": sum(rev_c_antes_que_d(resultados[q["pregunta"]], 10) for q in suite),
              "rev_c_en_top5": sum(any(c.startswith("TX350-C ") for c in resultados[q["pregunta"]][:5]) for q in suite),
              "no_aplica_en_top5": sum(any(c in NO_APLICAN for c in resultados[q["pregunta"]][:5]) for q in suite)}
    if detalle:
        salida["fallas@5"] = [{"id": f["id"], "top": f["top"]} for f in r["preguntas"] if not f["hit@5"]]
    print(f"  {nombre:28} hit@5={r['total']['hit@5']:.3f} recall@5={r['total']['recall@5']:.3f} "
          f"mrr={r['total']['mrr']:.3f} dis@5={r['total']['distractor@5']:.3f} "
          f"C<D@10={salida['rev_c_antes_que_d@10']} C@5={salida['rev_c_en_top5']} NA@5={salida['no_aplica_en_top5']}")
    return salida


async def correr_config(url: str, modelo: str, listas, filtros: Filtros, opciones: dict, suite: list[dict],
                        embedder: Embedder) -> tuple[dict[str, list[str]], float]:
    b = BuscadorManuales(url, embedder=embedder, listas=listas, **opciones)
    try:
        await b.citas("calentamiento", 20, filtros)
        t0 = time.perf_counter()
        resultados = {q["pregunta"]: await b.citas(q["pregunta"], 20, filtros) for q in suite}
        return resultados, (time.perf_counter() - t0) / len(suite)
    finally:
        await b.cerrar()


async def evaluar_todo(url: str, modelos: list[str], suite: list[dict], frags: list[dict]) -> dict:
    salida = {"bm25": resumir("bm25 (línea de base)", {q["pregunta"]: BM25(frags).buscar(q["pregunta"], 20)
                                                      for q in suite}, suite)}
    for clave in modelos:
        modelo = MODELOS[clave]
        embedder = Embedder(modelo, hilos=HILOS)
        print(await asegurar_indice(url, modelo=modelo, embedder=embedder))
        print(f"Modelo {clave}:")
        for nombre, (listas, filtros, opciones) in CONFIGS.items():
            if clave != modelos[0] and nombre not in CONFIGS_COMPARACION:
                continue
            resultados, latencia = await correr_config(url, clave, listas, filtros, opciones, suite, embedder)
            etiqueta = nombre if "sem" not in listas else f"{nombre}[{clave}]"
            salida[etiqueta] = resumir(etiqueta, resultados, suite, detalle=nombre == "hibrida") | {
                "latencia_ms": round(latencia * 1000, 1), "modelo": clave if "sem" in listas else None}
    return salida


def medir_modelo(clave: str) -> dict:
    """Carga el modelo en este proceso y mide RAM y latencia de las consultas de la suite (2 hilos)."""
    import psutil

    proc = psutil.Process()
    suite = json.loads((ruta_documentos() / "evaluacion" / "retrieval.json").read_text(encoding="utf-8"))
    rss0 = proc.memory_info().rss
    t0 = time.perf_counter()
    e = Embedder(clave, hilos=HILOS, cache_consultas=0)
    e.consulta("calentamiento")
    carga = time.perf_counter() - t0
    tiempos = []
    for q in suite:
        t = time.perf_counter()
        e.consulta(q["pregunta"])
        tiempos.append((time.perf_counter() - t) * 1000)
    info = proc.memory_info()
    pico = getattr(info, "peak_wset", None)
    if pico is None:
        import resource
        pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    m = MODELOS[clave]
    return {"modelo": m.nombre, "archivo": f"{m.repo}/{m.archivo}", "dim": m.dim, "max_tokens": m.max_tokens,
            "carga_s": round(carga, 2), "rss_base_mb": round(rss0 / 2**20), "rss_mb": round(info.rss / 2**20),
            "rss_modelo_mb": round((info.rss - rss0) / 2**20), "pico_mb": round(pico / 2**20),
            "latencia_consulta_ms_p50": round(statistics.median(tiempos), 1),
            "latencia_consulta_ms_p95": round(statistics.quantiles(tiempos, n=20)[18], 1), "hilos": HILOS}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelos", nargs="+", default=[MODELO_POR_DEFECTO, "minilm-l12", "jina-es-int8"],
                    choices=list(MODELOS))
    ap.add_argument("--url", default=os.environ.get("DATABASE_URL", URL_DESARROLLO))
    ap.add_argument("--medir-modelo", choices=list(MODELOS), help=argparse.SUPPRESS)
    ap.add_argument("--sin-medir", action="store_true", help="no mide RAM ni latencia de los modelos")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.medir_modelo:
        print(json.dumps(medir_modelo(a.medir_modelo)))
        return

    base = ruta_documentos()
    suite = json.loads((base / "evaluacion" / "retrieval.json").read_text(encoding="utf-8"))
    frags = [json.loads(x) for x in (base / "fragmentos.jsonl").read_text(encoding="utf-8").splitlines() if x]
    recursos = {}
    if not a.sin_medir:
        for clave in a.modelos:
            r = subprocess.run([sys.executable, __file__, "--medir-modelo", clave], capture_output=True, text=True,
                               encoding="utf-8", env=os.environ | {"PYTHONIOENCODING": "utf-8"}, check=True)
            recursos[clave] = json.loads(r.stdout.strip().splitlines()[-1])
            print(f"{clave}: {recursos[clave]}")
    configs = correr(evaluar_todo(a.url, a.modelos, suite, frags))
    resultado = {"fecha": datetime.now().isoformat(timespec="seconds"), "preguntas": len(suite),
                 "fragmentos": len(frags), "ks": KS, "hilos": HILOS, "modelos": recursos, "configuraciones": configs}
    if a.sin_medir and SALIDA.exists():
        resultado["modelos"] = json.loads(SALIDA.read_text(encoding="utf-8")).get("modelos", {})
    SALIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {SALIDA}")


if __name__ == "__main__":
    main()
