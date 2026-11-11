"""Transcripción local de las notas de voz."""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import time
import wave

import numpy as np

log = logging.getLogger(__name__)
SR = 16000
PROMPT = ("Recorrida de la planta de inyección: la uno, la dos, la tres, el filtro A, el filtro B, el pulmón. "
          "La dos está en mil seiscientos psi de descarga. El filtro B me dio uno ocho de diferencial. "
          "Empaquetadura, rodamiento, correas.")


def wav_a_audio(contenido: bytes) -> np.ndarray:
    """WAV PCM 16 bits → float32 mono a 16 kHz."""
    with wave.open(io.BytesIO(contenido), "rb") as w:
        canales, ancho, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        datos = w.readframes(w.getnframes())
    if ancho != 2:
        raise ValueError(f"WAV de {ancho * 8} bits: se esperaba PCM 16")
    audio = np.frombuffer(datos, dtype=np.int16).astype(np.float32) / 32768
    if canales > 1:
        audio = audio.reshape(-1, canales).mean(axis=1)
    if sr != SR:
        n = int(len(audio) * SR / sr)
        audio = np.interp(np.linspace(0, len(audio), n, endpoint=False), np.arange(len(audio)), audio).astype(np.float32)
    return audio


class Transcriptor:
    nombre: str

    def transcribir(self, audio: np.ndarray) -> tuple[str, int]:
        """(texto, tokens generados)."""
        raise NotImplementedError

    async def transcribir_async(self, audio: np.ndarray) -> tuple[str, int, float]:
        t0 = time.perf_counter()
        texto, tokens = await asyncio.to_thread(self.transcribir, audio)
        return texto.strip(), tokens, time.perf_counter() - t0


class Whisper(Transcriptor):
    def __init__(self, tamano: str, hilos: int):
        from faster_whisper import WhisperModel

        self.nombre = f"faster-whisper {tamano} int8"
        self.modelo = WhisperModel(tamano, device="cpu", compute_type="int8", cpu_threads=hilos)

    def transcribir(self, audio: np.ndarray) -> tuple[str, int]:
        segmentos, _ = self.modelo.transcribe(audio, language="es", beam_size=5, vad_filter=False,
                                              initial_prompt=PROMPT, condition_on_previous_text=False)
        segmentos = list(segmentos)
        return " ".join(s.text.strip() for s in segmentos), sum(len(s.tokens) for s in segmentos)


class Parakeet(Transcriptor):
    def __init__(self, hilos: int):
        import onnx_asr
        import onnxruntime as ort

        self.nombre = "parakeet-tdt-0.6b-v3 int8 (onnx-asr)"
        opciones = ort.SessionOptions()
        opciones.intra_op_num_threads = hilos
        self.modelo = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8", sess_options=opciones)

    def transcribir(self, audio: np.ndarray) -> tuple[str, int]:
        return self.modelo.recognize(audio, sample_rate=SR), 0


def crear(modelo: str, hilos: int) -> Transcriptor:
    if modelo.startswith("whisper:"):
        return Whisper(modelo.split(":", 1)[1], hilos)
    if modelo == "parakeet":
        return Parakeet(hilos)
    raise ValueError(f"STT_MODELO desconocido: {modelo}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--descargar", metavar="MODELO", help="descarga el modelo (se usa al construir la imagen)")
    a = ap.parse_args()
    if a.descargar:
        t = crear(a.descargar, 1)
        print(t.nombre, "→", repr(t.transcribir(np.zeros(SR, dtype=np.float32))))
