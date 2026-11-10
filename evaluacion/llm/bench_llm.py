"""Compara LLM locales en la extracción del parte, con el mismo criterio que usa el operador virtual.

    python evaluacion/llm/bench_llm.py --capturas .local/capturas --modelos qwen3.5:2b gemma4:e2b \
        --planta-sim ../academia2026-tp/planta/sim --salida evaluacion/llm/resultados
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

from sistema.dominio.planta import Planta
from sistema.llm.modelo import ModeloLocal
from sistema.procesamiento.parte import INSTRUCCIONES, Dictado, armar_borrador, preparar_texto


def cargar(capturas: Path, escenarios: list[str] | None) -> list[dict]:
    notas = []
    for f in sorted(capturas.glob("*/verdad.json")):
        if escenarios and f.parent.name not in escenarios:
            continue
        for v in json.loads(f.read_text(encoding="utf-8")):
            if "recorrida_id" in v and v.get("tipo") != "vivo" and not v.get("seguridad"):
                notas.append(v | {"escenario": f.parent.name})
    return notas


async def evaluar_modelo(nombre: str, notas: list[dict], planta: Planta, url: str, comparar, textos: dict | None):
    modelo = ModeloLocal(url, nombre)
    await modelo.estructurado(INSTRUCCIONES, "<nota>La uno está en 110 de descarga.</nota>", Dictado, "calentamiento")
    filas_salida = []
    for n in notas:
        texto = preparar_texto((textos or {}).get(n["nota_id"], n["texto"]))
        dictado, paso = await modelo.estructurado(INSTRUCCIONES, f"<nota>{texto}</nota>", Dictado, "extraccion")
        borrador = armar_borrador(dictado, planta, n.get("fotos", [])) if dictado else []
        ambigua_verdad = bool(n.get("ambiguedades"))
        ambigua_pred = any(f.ambigua for f in borrador)
        # Las filas ambiguas se resuelven con la respuesta correcta, como haría el operador.
        tags_ambiguos = {a["tag"] for a in n.get("ambiguedades", []) if a["tipo"] == "equipo"}
        mostradas = []
        for f in borrador:
            tag = f.tag or (next(iter(tags_ambiguos & set(f.candidatos)), None) if f.candidatos else None)
            if f.valor is not None and tag:
                mostradas.append({"tag": tag, "valor": f.valor, "unidad": f.unidad})
        esperados = [i for i in n["items"] if i.get("valor") is not None]
        problemas = comparar(mostradas, esperados)
        filas_salida.append({
            "nota_id": n["nota_id"], "escenario": n["escenario"], "texto": texto, "ok": not problemas,
            "problemas": problemas, "ambigua_verdad": ambigua_verdad, "ambigua_pred": ambigua_pred,
            "latencia_s": paso.duracion_ms / 1000, "tokens_entrada": paso.tokens_entrada,
            "tokens_salida": paso.tokens_salida, "json_ok": paso.ok,
            "filas": [vars(f) for f in borrador]})
        print(f"{nombre:16} {paso.duracion_ms / 1000:5.1f}s {'OK ' if not problemas else 'MAL'} "
              f"amb {int(ambigua_verdad)}/{int(ambigua_pred)} | {texto[:90]}", flush=True)
    lat = sorted(f["latencia_s"] for f in filas_salida)
    amb = [f for f in filas_salida if f["ambigua_verdad"]]
    claras = [f for f in filas_salida if not f["ambigua_verdad"]]
    resumen = {
        "modelo": nombre, "notas": len(filas_salida),
        "parte_ok": round(sum(f["ok"] for f in filas_salida) / len(filas_salida), 3),
        "json_ok": round(sum(f["json_ok"] for f in filas_salida) / len(filas_salida), 3),
        "detecta_ambiguas": f"{sum(f['ambigua_pred'] for f in amb)}/{len(amb)}",
        "pregunta_de_mas": f"{sum(f['ambigua_pred'] for f in claras)}/{len(claras)}",
        "latencia_p50_s": round(statistics.median(lat), 1), "latencia_p95_s": round(lat[int(0.95 * (len(lat) - 1))], 1),
        "tokens_entrada_prom": round(statistics.mean(f["tokens_entrada"] for f in filas_salida)),
        "tokens_salida_prom": round(statistics.mean(f["tokens_salida"] for f in filas_salida)),
    }
    return resumen, filas_salida


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capturas", type=Path, required=True)
    ap.add_argument("--modelos", nargs="+", required=True)
    ap.add_argument("--escenarios", nargs="*")
    ap.add_argument("--planta-sim", type=Path, default=Path("../academia2026-tp/planta/sim"))
    ap.add_argument("--definicion", type=Path, default=Path("datos/planta.yaml"))
    ap.add_argument("--ollama", default="http://localhost:11434")
    ap.add_argument("--textos", type=Path, help="JSON {nota_id: transcripción} para evaluar sobre la salida del STT")
    ap.add_argument("--limite", type=int)
    ap.add_argument("--salida", type=Path, required=True)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(a.planta_sim.resolve()))
    from planta_sim.dialogo import _comparar  # el mismo criterio del operador virtual

    import yaml
    planta = Planta.desde_definicion(yaml.safe_load(a.definicion.read_text(encoding="utf-8")))
    notas = cargar(a.capturas, a.escenarios)[: a.limite]
    textos = json.loads(a.textos.read_text(encoding="utf-8")) if a.textos else None
    a.salida.mkdir(parents=True, exist_ok=True)
    resumenes = []
    for m in a.modelos:
        resumen, filas = await evaluar_modelo(m, notas, planta, a.ollama, _comparar, textos)
        sufijo = "-stt" if textos else ""
        (a.salida / f"{m.replace(':', '_')}{sufijo}.json").write_text(
            json.dumps({"resumen": resumen, "notas": filas}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        resumenes.append(resumen)
    print(json.dumps(resumenes, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
