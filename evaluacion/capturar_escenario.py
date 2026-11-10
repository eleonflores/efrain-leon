"""Corre un escenario de la planta sin el sistema y guarda la verdad de campo y los audios de las notas.

    python evaluacion/capturar_escenario.py martes-tranquilo --salida .local/capturas
    python evaluacion/capturar_escenario.py libre --horas 72 --salida .local/capturas
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import yaml

DURACION = {"h": 1, "m": 1 / 60}


def horas_del_escenario(repo_planta: Path, nombre: str) -> float | None:
    d = yaml.safe_load((repo_planta / "escenarios" / f"{nombre}.yaml").read_text(encoding="utf-8")).get("duracion")
    return float(d[:-1]) * DURACION[d[-1]] if d else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("escenario")
    ap.add_argument("--salida", type=Path, required=True)
    ap.add_argument("--api", default="http://localhost:8100")
    ap.add_argument("--repo-planta", type=Path, default=Path("../academia2026-tp"))
    ap.add_argument("--horas", type=float, help="obligatorio para escenarios sin duración (libre)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    http = httpx.Client(base_url=a.api, timeout=300)
    estado = lambda: http.get("/api/estado").json()  # noqa: E731

    def pausar(pausa: bool) -> None:
        if estado().get("pausado") != pausa:
            http.post("/api/control/pausa")

    horas = a.horas or horas_del_escenario(a.repo_planta, a.escenario)
    if horas is None:
        raise SystemExit("Este escenario no termina solo: pasá --horas")
    pausar(True)
    http.post(f"/api/control/escenario/{a.escenario}").raise_for_status()
    pausar(True)
    http.post("/api/control/auto-lento", json={"activo": False})
    http.post("/api/control/reloj-eventos",
              json={"rapida": 1800, "lenta": 5, "silencio_s": 5, "minimo_s": 3, "maximo_s": 120})
    inicio = datetime.fromisoformat(estado()["ts"])
    fin = inicio + timedelta(hours=horas)
    print(f"{a.escenario}: {inicio:%d/%m %H:%M} → {fin:%d/%m %H:%M}", flush=True)
    pausar(False)
    t0 = time.time()
    while (ahora := datetime.fromisoformat(estado()["ts"])) < fin - timedelta(seconds=20):
        print(f"\r  {ahora:%d/%m %H:%M} · {(ahora - inicio) / (fin - inicio):5.1%} · {time.time() - t0:4.0f} s", end="",
              flush=True)
        time.sleep(3)
    pausar(True)

    verdad = http.get("/api/verdad").json()
    destino = a.salida / a.escenario
    (destino / "audios").mkdir(parents=True, exist_ok=True)
    notas = [v for v in verdad if "recorrida_id" in v]
    for n in notas:
        if n.get("audio_url"):
            (destino / "audios" / Path(n["audio_url"]).name).write_bytes(http.get(n["audio_url"]).content)
    (destino / "verdad.json").write_text(json.dumps(verdad, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  {len(notas)} notas ({sum(bool(n.get('ambiguedades')) for n in notas)} ambiguas, "
          f"{sum(bool(n.get('seguridad')) for n in notas)} de seguridad) en {destino} · {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
