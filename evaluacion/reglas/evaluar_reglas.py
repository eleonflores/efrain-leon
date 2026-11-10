"""Evalúa la extracción por reglas y la detección sobre notas generadas por el operador virtual de la planta.

Genera recorridas con el mismo código de la planta (`planta_sim.operador.OperadorVirtual` sobre `planta_sim.modelo`),
con fallas al azar, bombas paradas y ambigüedades, y mide con los criterios de la corrección:

- A2: el primer borrador se confirmaría (`planta_sim.dialogo._comparar`, el mismo criterio del operador);
- A4: detecta las ambigüedades y no pregunta en las notas claras;
- B1: la decisión SinNovedad/Escalado por equipo coincide con la del corrector (`correccion/puntuar.py`);
- cuántas notas no resuelven las reglas y van al LLM.

    python evaluacion/reglas/evaluar_reglas.py --repo-planta ../academia2026-tp --notas 400
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from sistema.dominio.deteccion import evaluar_parte
from sistema.dominio.planta import Planta
from sistema.procesamiento import reglas_parte
from sistema.procesamiento.parte import armar_borrador, preparar_texto

FALLAS = ["F01", "F02", "F03", "F04", "F05", "F06", "F07", "F09"]


def generar(repo: Path, cantidad: int, semilla: int) -> list[dict]:
    sys.path.insert(0, str(repo / "planta/sim"))
    from planta_sim.modelo import Planta as PlantaSim
    from planta_sim.operador import OperadorVirtual

    definicion = yaml.safe_load((repo / "datos/planta.yaml").read_text(encoding="utf-8"))
    rng = random.Random(semilla)
    notas: list[dict] = []
    while len(notas) < cantidad:
        p = PlantaSim.desde_definicion(definicion, random.Random(rng.random()), datetime(2026, 11, 3, 8, tzinfo=timezone.utc))
        for _ in range(rng.choice([0, 1, 1, 2])):
            codigo = rng.choice(FALLAS)
            equipos = ["F-201A", "F-201B"] if codigo == "F07" else ["B-101", "B-102", "B-103"]
            p.agregar_falla(codigo, rng.choice(equipos), rng.uniform(0.2, 0.9), 0.0)
        if rng.random() < 0.3:
            b = p.bombas[rng.choice(["B-101", "B-102", "B-103"])]
            b.estado = rng.choice(["parada", "mantenimiento", "disparo"])
        for _ in range(rng.randint(60, 400)):
            p.paso(10.0)
        operador = OperadorVirtual(random.Random(rng.random()), random.Random(rng.random()))
        for n in operador.recorrida(p):
            notas.append(n.esperado())
    return notas[:cantidad]


def anomalos_corrector(nota: dict, limites: dict) -> dict[str, bool]:
    """La misma regla de `correccion/puntuar.py` (anomalos + fuera_de_limite)."""
    a_kg = {"kg/cm2": 1.0, "psi": 1 / 14.2233, "bar": 1.01972}
    normales = {"parada, en reserva", "parada por mantenimiento"}
    variables = {"presion_descarga_local": "presion_descarga", "presion_diferencial": "presion_diferencial"}
    salida: dict[str, bool] = {}
    for i in nota["items"]:
        fuera = False
        sensor = variables.get(i["variable"])
        if sensor and i.get("valor") is not None and (i["tag"], sensor) in limites:
            lim, v = limites[(i["tag"], sensor)], i["valor"] * a_kg.get(i.get("unidad") or "kg/cm2", 1.0)
            fuera = (lim.get("alarma_alta") is not None and v >= lim["alarma_alta"]) or \
                    (lim.get("alarma_baja") is not None and v <= lim["alarma_baja"])
        anomalo = (i.get("observacion") is not None and i["observacion"] not in normales) or fuera
        salida[i["tag"]] = salida.get(i["tag"], False) or anomalo
    return salida


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-planta", type=Path, default=Path("../academia2026-tp"))
    ap.add_argument("--notas", type=int, default=400)
    ap.add_argument("--semilla", type=int, default=7)
    ap.add_argument("--salida", type=Path, default=Path("evaluacion/reglas/resultados.json"))
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    repo = a.repo_planta.resolve()
    notas = generar(repo, a.notas, a.semilla)
    from planta_sim.dialogo import _comparar

    definicion = yaml.safe_load((repo / "datos/planta.yaml").read_text(encoding="utf-8"))
    planta = Planta.desde_definicion(definicion)
    limites = {(s["tag"], s["variable"]): s for s in definicion["sensores"]}

    cont = Counter()
    fallas = []
    for n in notas:
        texto = preparar_texto(n["texto"])
        dictado = reglas_parte.extraer(texto, planta)
        if dictado is None:
            cont["al_llm"] += 1
            fallas.append({"tipo": "al_llm", "texto": n["texto"]})
            continue
        filas = armar_borrador(dictado, planta, n.get("fotos", []))
        ambigua_verdad, ambigua_pred = bool(n.get("ambiguedades")), any(f.ambigua for f in filas)
        cont["ambiguas"] += ambigua_verdad
        cont["detecta_ambigua"] += ambigua_verdad and ambigua_pred
        cont["pregunta_de_mas"] += (not ambigua_verdad) and ambigua_pred
        tags_amb = {x["tag"] for x in n.get("ambiguedades", []) if x["tipo"] == "equipo"}
        resueltas = []
        for f in filas:
            tag = f.tag or next(iter(tags_amb & set(f.candidatos)), None)
            resueltas.append({"tag": tag, "variable": f.variable, "valor": f.valor, "unidad": f.unidad,
                              "observacion": f.observacion})
        problemas = _comparar([r for r in resueltas if r["valor"] is not None and r["tag"]],
                              [i for i in n["items"] if i.get("valor") is not None])
        cont["notas"] += 1
        cont["borrador_ok"] += not problemas
        esperado = anomalos_corrector(n, limites)
        nuestro = {d.tag: d.tipo == "Escalado" for d in evaluar_parte([r for r in resueltas if r["tag"]], planta)}
        for tag, anomalo in esperado.items():
            cont["b1_total"] += 1
            cont["b1_ok"] += nuestro.get(tag, False) == anomalo
        if problemas or any(nuestro.get(t, False) != v for t, v in esperado.items()):
            fallas.append({"tipo": "error", "texto": n["texto"], "problemas": problemas,
                           "b1_esperado": esperado, "b1_nuestro": nuestro,
                           "filas": [(f.tag, f.variable, f.valor, f.unidad, f.observacion) for f in filas]})
    resumen = {
        "notas": len(notas), "resueltas_por_reglas": cont["notas"], "al_llm": cont["al_llm"],
        "primer_borrador_ok": f"{cont['borrador_ok']}/{cont['notas']}",
        "ambiguas_detectadas": f"{cont['detecta_ambigua']}/{cont['ambiguas']}",
        "pregunta_de_mas": cont["pregunta_de_mas"],
        "b1_ok": f"{cont['b1_ok']}/{cont['b1_total']}",
    }
    print(json.dumps(resumen, ensure_ascii=False, indent=1))
    for f in fallas[:25]:
        print("-", json.dumps(f, ensure_ascii=False)[:400])
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps({"resumen": resumen, "fallas": fallas}, ensure_ascii=False, indent=1),
                        encoding="utf-8")


if __name__ == "__main__":
    main()
