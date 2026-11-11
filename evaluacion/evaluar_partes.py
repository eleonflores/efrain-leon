"""Evalúa el parte por voz contra la verdad de campo.

Desde una corrida del corrector (trae la verdad y el registro de lo que publicó el sistema):

    python evaluacion/evaluar_partes.py --corrida ../academia2026-tp/correccion/corridas/<corrida>/martes-tranquilo.json         --salida evaluacion/partes/martes-tranquilo.json

O contra la planta en desarrollo (`/api/verdad` abierta), después de correr un escenario con el sistema levantado:

    python evaluacion/evaluar_partes.py --salida evaluacion/partes/martes-tranquilo.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

import httpx

A_KG = {"kg/cm2": 1.0, "psi": 1 / 14.2233, "bar": 1 / 0.980665}


def cerca(a, b, ua=None, ub=None) -> bool:
    """La misma tolerancia que usa el operador virtual."""
    if a is None or b is None:
        return False
    if ua in A_KG and ub in A_KG:
        return abs(a * A_KG[ua] - b * A_KG[ub]) <= max(0.6, abs(b * A_KG[ub]) * 0.02)
    return abs(a - b) <= max(0.051, abs(b) * 0.015)


def ts(x: str) -> datetime:
    return datetime.fromisoformat(x)


def percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    v = sorted(valores)
    return round(v[int(p * (len(v) - 1))], 2)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://localhost:8100")
    ap.add_argument("--corrida", type=Path, help="JSON de un escenario de una corrida del corrector")
    ap.add_argument("--salida", type=Path)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if a.corrida:
        corrida = json.loads(a.corrida.read_text(encoding="utf-8"))
        escenario, verdad, registro, estado = corrida["escenario"], corrida["verdad"], corrida["registro"], {}
    else:
        http = httpx.Client(base_url=a.api, timeout=60)
        verdad = http.get("/api/verdad").json()
        registro = http.get("/api/registro").json()
        estado = http.get("/api/estado").json()
        escenario = estado.get("escenario")

    notas = [v for v in verdad if "recorrida_id" in v and v.get("tipo") != "vivo"]
    dialogos = [v for v in verdad if v.get("tipo") == "dialogo"]
    tablet = [r for r in registro if r["topico"] == "sistema/tablet" and r["valido"]]
    eventos = [r for r in registro if r["topico"] == "sistema/eventos" and r["valido"]]

    campos = {"equipo": [0, 0], "valor": [0, 0], "unidad": [0, 0]}
    por_nota, lat_tablet, lat_alerta = [], [], []
    for n in notas:
        nid = n["nota_id"]
        mensajes = [r for r in tablet if nid in r["payload"].get("nota_ids", [])]
        borradores = [d for d in dialogos if nid in d.get("nota_ids", []) and d.get("filas_mostradas", 0) > 0]
        preguntas = [r for r in mensajes if r["payload"].get("espera_respuesta", True)
                     and (not (r["payload"].get("pantalla") or {}).get("filas")
                          or (r["payload"].get("pantalla") or {}).get("opciones"))]
        primero = next((r for r in mensajes if any(f.get("valor") is not None
                                                   for f in (r["payload"].get("pantalla") or {}).get("filas", []))), None)
        if mensajes:
            lat_tablet.append((ts(mensajes[0]["ts_real"]) - ts(n["ts_real"])).total_seconds())
        if n.get("seguridad"):
            alerta = next((r for r in eventos if r["payload"]["tipo"] == "AlertaSeguridad"
                           and nid in r["payload"].get("nota_ids", [])), None)
            if alerta:
                lat_alerta.append((ts(alerta["ts_real"]) - ts(n["ts_real"])).total_seconds())
        if primero:
            filas = [f for f in primero["payload"]["pantalla"]["filas"] if f.get("valor") is not None]
            for item in (i for i in n["items"] if i.get("valor") is not None):
                fila = next((f for f in filas if f["tag"] == item["tag"] and f["variable"] == item["variable"]),
                            None) or next((f for f in filas if cerca(f["valor"], item["valor"], f.get("unidad"),
                                                                      item.get("unidad"))), None)
                campos["equipo"][1] += 1
                campos["valor"][1] += 1
                campos["unidad"][1] += 1
                if fila:
                    campos["equipo"][0] += fila["tag"] == item["tag"]
                    campos["valor"][0] += cerca(fila["valor"], item["valor"], fila.get("unidad"), item.get("unidad"))
                    campos["unidad"][0] += fila.get("unidad") == item.get("unidad") or (
                        fila.get("unidad") in A_KG and item.get("unidad") in A_KG)
        por_nota.append({
            "nota": nid, "texto": n["texto"], "seguridad": n.get("seguridad"), "ambigua": bool(n.get("ambiguedades")),
            "mensajes": len(mensajes), "pregunto": bool(preguntas), "borradores": len(borradores),
            "primer_borrador_confirmado": bool(borradores and borradores[0].get("confirmo")),
            "confirmado_al_final": bool(borradores and borradores[-1].get("confirmo")),
            "problemas_primer_borrador": borradores[0].get("problemas") if borradores else None,
            "eventos": sorted({(e["payload"]["tipo"], e["payload"].get("equipo")) for e in eventos
                               if nid in e["payload"].get("nota_ids", [])}, key=str),
        })

    comunes = [p for p in por_nota if not p["seguridad"]]
    ambiguas = [p for p in comunes if p["ambigua"]]
    claras = [p for p in comunes if not p["ambigua"]]
    resumen = {
        "escenario": escenario, "notas": len(notas), "con_mensaje_en_tablet": sum(p["mensajes"] > 0 for p in por_nota),
        "primer_borrador_confirmado": sum(p["primer_borrador_confirmado"] for p in comunes),
        "confirmado_al_final": sum(p["confirmado_al_final"] for p in comunes), "notas_comunes": len(comunes),
        "aciertos_por_campo": {k: f"{v[0]}/{v[1]}" for k, v in campos.items()},
        "pregunto_en_ambiguas": f"{sum(p['pregunto'] for p in ambiguas)}/{len(ambiguas)}",
        "pregunto_de_mas": f"{sum(p['pregunto'] for p in claras)}/{len(claras)}",
        "latencia_tablet_s": {"p50": percentil(lat_tablet, 0.5), "p95": percentil(lat_tablet, 0.95)},
        "latencia_alerta_s": lat_alerta,
        "mensajes_invalidos": sum(not r["valido"] for r in registro),
        "costo_usd": 0.0,
        "consumo_tokens": (estado.get("sistema") or {}).get("consumo_tokens"),
    }
    print(json.dumps(resumen, ensure_ascii=False, indent=1))
    for p in por_nota:
        if not p["primer_borrador_confirmado"] and not p["seguridad"]:
            print(f"- {p['nota']}: {p['texto'][:110]} → {p['problemas_primer_borrador']}")
    if a.salida:
        a.salida.parent.mkdir(parents=True, exist_ok=True)
        a.salida.write_text(json.dumps({"resumen": resumen, "notas": por_nota}, ensure_ascii=False, indent=1),
                            encoding="utf-8")


if __name__ == "__main__":
    main()
