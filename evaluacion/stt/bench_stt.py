"""Compara modelos de transcripción sobre las notas de voz de la planta.

Usa el banco de voces de la planta (`datos/voces/`: 102 notas con su texto) y les mezcla el mismo ruido de planta que
agrega el simulador (`planta_sim.audio.ruido_planta`, intensidad 0,45–0,7 como en `nota_a_wav`). Corre un modelo por
invocación, así la memoria pico es solo la de ese modelo.

    python bench_stt.py --modelo whisper:small --voces /voces --salida /resultados/whisper-small.json

Modelos: `whisper:<tamaño>` (faster-whisper, int8) y `parakeet` (Parakeet TDT 0.6B v3 con onnx-asr).
Métricas: WER sobre texto normalizado (números en dígitos), notas con todos los números bien, recall de números,
latencia por nota (p50/p95), factor de tiempo real y memoria pico.
"""

from __future__ import annotations

import argparse
import json
import re
import resource
import statistics
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

from sistema.procesamiento.numeros import extraer_numeros, normalizar_numeros, sin_tildes

SR = 16000
from sistema.procesamiento.stt import PROMPT  # el mismo prompt que usa el sistema
_PROMPT_VIEJO = ("Recorrida de la planta de inyección: la uno, la dos, la tres, el filtro A, el filtro B, el pulmón. "
          "Descarga en kilos, psi o bar; diferencial; empaquetadura; rodamiento; correas.")


def normalizar(texto: str) -> str:
    t = sin_tildes(normalizar_numeros(texto).lower())
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)          # puntos que no son decimales
    t = re.sub(r"[^\w.\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def con_ruido(habla: np.ndarray, semilla: int, golpeteo: bool) -> np.ndarray:
    from planta_sim.audio import ruido_planta

    rng = np.random.default_rng(semilla)
    habla = habla / max(1e-3, float(np.abs(habla).max())) * 0.85
    intensidad = rng.uniform(0.45, 0.7)
    pre, post = int(SR * rng.uniform(0.4, 1.0)), int(SR * rng.uniform(0.5, 1.2))
    mezcla = ruido_planta(pre + len(habla) + post, rng, intensidad=intensidad, golpeteo=golpeteo)
    mezcla[pre:pre + len(habla)] += habla
    return np.clip(mezcla / max(1.0, float(np.abs(mezcla).max()) / 0.95), -1, 1).astype(np.float32)


def cargar_notas(voces: Path, limite: int | None, sin_ruido: bool) -> list[dict]:
    indice = json.loads((voces / "indice.json").read_text(encoding="utf-8"))
    notas = []
    for clave, meta in sorted(indice.items())[:limite]:
        habla, sr = sf.read(voces / f"{clave}.flac", dtype="float32")
        assert sr == SR, sr
        if habla.ndim > 1:
            habla = habla.mean(axis=1)
        golpeteo = any(p in meta["texto"].lower() for p in ("golpeteo", "piedras", "ruido raro"))
        audio = habla if sin_ruido else con_ruido(habla, zlib.crc32(clave.encode()), golpeteo)
        notas.append({"clave": clave, "texto": meta["texto"], "escenario": meta.get("escenario"), "audio": audio})
    return notas


def cargar_modelo(nombre: str, hilos: int, beam: int, prompt: bool):
    if nombre.startswith("whisper:"):
        from faster_whisper import WhisperModel

        modelo = WhisperModel(nombre.split(":", 1)[1], device="cpu", compute_type="int8", cpu_threads=hilos)

        def transcribir(audio: np.ndarray) -> str:
            segmentos, _ = modelo.transcribe(audio, language="es", beam_size=beam, vad_filter=False,
                                             initial_prompt=PROMPT if prompt else None,
                                             condition_on_previous_text=False)
            return " ".join(s.text.strip() for s in segmentos)
        return transcribir
    if nombre == "parakeet":
        import onnx_asr
        import onnxruntime as ort

        opciones = ort.SessionOptions()
        opciones.intra_op_num_threads = hilos
        modelo = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8", sess_options=opciones)

        def transcribir(audio: np.ndarray) -> str:
            return modelo.recognize(audio, sample_rate=SR)
        return transcribir
    raise SystemExit(f"Modelo desconocido: {nombre}")


def wer(ref: str, hip: str) -> tuple[int, int]:
    import jiwer

    if not ref.split():
        return 0, 0
    salida = jiwer.process_words(ref, hip)
    return salida.substitutions + salida.deletions + salida.insertions, len(ref.split())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modelo", required=True)
    ap.add_argument("--voces", type=Path, default=Path("/voces"))
    ap.add_argument("--salida", type=Path, required=True)
    ap.add_argument("--limite", type=int)
    ap.add_argument("--hilos", type=int, default=4)
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--sin-prompt", action="store_true")
    ap.add_argument("--sin-ruido", action="store_true")
    a = ap.parse_args()

    notas = cargar_notas(a.voces, a.limite, a.sin_ruido)
    t0 = time.perf_counter()
    transcribir = cargar_modelo(a.modelo, a.hilos, a.beam, not a.sin_prompt)
    carga_s = time.perf_counter() - t0
    transcribir(notas[0]["audio"][: SR * 2])          # calentamiento, no se mide

    filas, errores, palabras = [], 0, 0
    numeros_bien, numeros_total, numeros_hallados = 0, 0, 0
    for n in notas:
        t = time.perf_counter()
        hip = transcribir(n["audio"])
        dur = time.perf_counter() - t
        ref_n, hip_n = normalizar(n["texto"]), normalizar(hip)
        e, p = wer(ref_n, hip_n)
        errores, palabras = errores + e, palabras + p
        nr, nh = extraer_numeros(n["texto"]), extraer_numeros(hip)
        numeros_bien += nr == nh
        numeros_total += len(nr)
        numeros_hallados += sum((Counter(nr) & Counter(nh)).values())
        filas.append({"clave": n["clave"], "escenario": n["escenario"], "audio_s": round(len(n["audio"]) / SR, 2),
                      "latencia_s": round(dur, 3), "wer": round(e / p, 3) if p else 0, "numeros_ok": nr == nh,
                      "ref": n["texto"], "hip": hip, "ref_numeros": nr, "hip_numeros": nh})
        print(f"{dur:5.2f}s wer={e / max(p, 1):.2f} num={'ok' if nr == nh else 'MAL'} | {hip}", flush=True)

    lat = sorted(f["latencia_s"] for f in filas)
    audio_total = sum(f["audio_s"] for f in filas)
    resumen = {
        "modelo": a.modelo, "hilos": a.hilos, "beam": a.beam, "prompt": not a.sin_prompt, "ruido": not a.sin_ruido,
        "notas": len(filas), "wer": round(errores / palabras, 4),
        "notas_con_numeros_ok": round(numeros_bien / len(filas), 3),
        "recall_numeros": round(numeros_hallados / max(numeros_total, 1), 3),
        "latencia_p50_s": round(statistics.median(lat), 2), "latencia_p95_s": round(lat[int(0.95 * (len(lat) - 1))], 2),
        "latencia_max_s": round(lat[-1], 2), "rtf": round(sum(lat) / audio_total, 3),
        "audio_promedio_s": round(audio_total / len(filas), 1), "carga_modelo_s": round(carga_s, 1),
        "ram_pico_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        "python": sys.version.split()[0],
    }
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps({"resumen": resumen, "notas": filas}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
