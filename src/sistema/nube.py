"""El lado "nube": recibe lo que la planta sincroniza cuando hay enlace.

En la Entrega 1 guarda los eventos escalados y las alertas que llegan de la planta (con su contexto). En la Entrega 2
acá corre el análisis de la anomalía. No está en la red de planta: la planta lo alcanza solo a través del proxy del
enlace (`enlace:3128`), así que cuando el enlace se cae no llega nada y la planta acumula pendientes.

    python -m sistema.nube        # escucha en :8000
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

log = logging.getLogger("nube")
DATOS = Path(os.environ.get("NUBE_DATOS", "/datos"))


class Manejador(BaseHTTPRequestHandler):
    recibidos: dict[str, dict] = {}

    def _responder(self, codigo: int, cuerpo: dict) -> None:
        datos = json.dumps(cuerpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/salud":
            return self._responder(200, {"ok": True})
        if self.path == "/eventos":
            return self._responder(200, {"eventos": list(self.recibidos.values())})
        self._responder(404, {"error": "no existe"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/eventos":
            return self._responder(404, {"error": "no existe"})
        cuerpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        nuevo = cuerpo.get("id") not in self.recibidos
        self.recibidos[cuerpo["id"]] = cuerpo | {"recibido": datetime.now(timezone.utc).isoformat()}
        if nuevo:
            DATOS.mkdir(parents=True, exist_ok=True)
            with (DATOS / "eventos.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(self.recibidos[cuerpo["id"]], ensure_ascii=False) + "\n")
            log.info("Recibido %s (%s)", cuerpo["id"], cuerpo.get("tipo"))
        self._responder(200, {"ok": True, "nuevo": nuevo})   # idempotente: el mismo id no se duplica

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    puerto = int(os.environ.get("NUBE_PUERTO", "8000"))
    log.info("Nube escuchando en :%s", puerto)
    ThreadingHTTPServer(("0.0.0.0", puerto), Manejador).serve_forever()


if __name__ == "__main__":
    main()
