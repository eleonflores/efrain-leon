"""Comandos del índice del RAG.

    python -m sistema.rag.indexar --precalcular              # embebe el corpus (al construir la imagen)
    python -m sistema.rag.indexar --cargar                   # carga Postgres ($DATABASE_URL) si hace falta
    python -m sistema.rag.indexar --cargar --forzar          # borra y vuelve a cargar
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from sistema.rag.corpus import cargar_corpus
from sistema.rag.embeddings import MODELOS, Embedder, modelo_configurado, precalcular


def correr(corrutina):
    """`asyncio.run` con el loop que psycopg acepta en Windows (`SelectorEventLoop`)."""
    if sys.platform == "win32":
        return asyncio.run(corrutina, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(corrutina)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--precalcular", action="store_true", help="embebe el corpus y guarda el .npz")
    ap.add_argument("--cargar", action="store_true", help="carga el índice en Postgres si está vacío o vencido")
    ap.add_argument("--forzar", action="store_true", help="con --cargar: recarga aunque esté al día")
    ap.add_argument("--modelo", choices=list(MODELOS), default=None, help="por defecto $RAG_MODELO o e5-small-int8")
    ap.add_argument("--hilos", type=int, default=None, help="hilos de onnxruntime (por defecto $RAG_HILOS o 2)")
    ap.add_argument("--url", default=None, help="por defecto $DATABASE_URL")
    a = ap.parse_args()
    if not (a.precalcular or a.cargar):
        ap.error("indicá --precalcular y/o --cargar")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.stdout.reconfigure(encoding="utf-8")
    modelo = MODELOS[a.modelo] if a.modelo else modelo_configurado()

    if a.precalcular:
        corpus = cargar_corpus()
        t0 = time.perf_counter()
        ruta = precalcular(corpus, Embedder(modelo, hilos=a.hilos))
        print(f"{len(corpus)} fragmentos embebidos con {modelo.nombre} en {time.perf_counter() - t0:.1f} s → {ruta}")
    if a.cargar:
        from sistema.config import CONFIG
        from sistema.rag.indice import asegurar_indice

        estado = correr(asegurar_indice(a.url or CONFIG.database_url, modelo=modelo, forzar=a.forzar))
        print(estado)


if __name__ == "__main__":
    main()
