"""Modelo de embeddings local (ONNX en CPU, dentro del proceso Python) y los vectores precalculados del corpus."""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sistema.rag.corpus import Corpus, ruta_documentos

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModeloEmbeddings:
    clave: str
    nombre: str
    repo: str
    archivo: str
    dim: int
    max_tokens: int
    prefijo_consulta: str = ""
    prefijo_pasaje: str = ""
    nativo_fastembed: bool = False

    def archivo_vectores(self, base: Path | None = None) -> Path:
        return (base or ruta_documentos()) / f"embeddings_{self.clave}.npz"


MODELOS: dict[str, ModeloEmbeddings] = {m.clave: m for m in (
    # E5 se entrenó con prefijos: "query: " para la pregunta y "passage: " para el texto indexado.
    ModeloEmbeddings("e5-small-int8", "intfloat/multilingual-e5-small", "Xenova/multilingual-e5-small",
                     "onnx/model_quantized.onnx", 384, 512, "query: ", "passage: "),
    ModeloEmbeddings("minilm-l12", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                     "Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q", "model_optimized.onnx", 384, 128,
                     nativo_fastembed=True),
    ModeloEmbeddings("jina-es-int8", "jinaai/jina-embeddings-v2-base-es-int8", "jinaai/jina-embeddings-v2-base-es",
                     "onnx/model_quantized.onnx", 768, 512),
)}
MODELO_POR_DEFECTO = "e5-small-int8"


def modelo_configurado() -> ModeloEmbeddings:
    clave = os.environ.get("RAG_MODELO", MODELO_POR_DEFECTO)
    if clave not in MODELOS:
        raise ValueError(f"RAG_MODELO='{clave}' no existe; opciones: {', '.join(MODELOS)}")
    return MODELOS[clave]


def hilos_configurados() -> int:
    return int(os.environ.get("RAG_HILOS", "2"))


def cache_modelos() -> str | None:
    """Dónde guarda fastembed los modelos."""
    if os.environ.get("FASTEMBED_CACHE_PATH"):
        return os.environ["FASTEMBED_CACHE_PATH"]
    if os.environ.get("HF_HOME"):
        return str(Path(os.environ["HF_HOME"]).parent / "fastembed")
    return None


class Embedder:
    """Envoltura de `fastembed.TextEmbedding`: carga perezosa, prefijos del modelo, vectores normalizados (coseno)."""

    def __init__(self, modelo: ModeloEmbeddings | str | None = None, *, hilos: int | None = None,
                 cache_dir: str | None = None, cache_consultas: int = 256):
        self.modelo = MODELOS[modelo] if isinstance(modelo, str) else (modelo or modelo_configurado())
        self.hilos = hilos or hilos_configurados()
        self.cache_dir = cache_dir or cache_modelos()
        self._motor = None
        self._lock = threading.Lock()
        self._consultas: OrderedDict[str, np.ndarray] = OrderedDict()
        self._max_cache = cache_consultas

    def _cargar(self):
        with self._lock:
            if self._motor is None:
                from fastembed import TextEmbedding
                from fastembed.common.model_description import ModelSource, PoolingType

                m = self.modelo
                registrados = {x["model"] for x in TextEmbedding.list_supported_models()}
                if not m.nativo_fastembed and m.nombre not in registrados:
                    TextEmbedding.add_custom_model(model=m.nombre, pooling=PoolingType.MEAN, normalization=True,
                                                   sources=ModelSource(hf=m.repo), dim=m.dim, model_file=m.archivo)
                log.info("Cargando el modelo de embeddings %s (%d hilos)", m.nombre, self.hilos)
                self._motor = TextEmbedding(m.nombre, cache_dir=self.cache_dir, threads=self.hilos)
        return self._motor

    def pasajes(self, textos: list[str], tamano_lote: int = 16) -> np.ndarray:
        motor = self._cargar()
        vectores = motor.embed([self.modelo.prefijo_pasaje + t for t in textos], batch_size=tamano_lote)
        return _normalizar(np.vstack(list(vectores)).astype(np.float32))

    def consulta(self, texto: str) -> np.ndarray:
        if texto in self._consultas:
            self._consultas.move_to_end(texto)
            return self._consultas[texto]
        vector = _normalizar(next(iter(self._cargar().embed([self.modelo.prefijo_consulta + texto])))
                             .astype(np.float32)[None, :])[0]
        self._consultas[texto] = vector
        if len(self._consultas) > self._max_cache:
            self._consultas.popitem(last=False)
        return vector


def _normalizar(m: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(normas == 0, 1, normas)


# ---------------------------------------------------------------- vectores precalculados

@dataclass
class VectoresCorpus:
    modelo: str
    huella: str
    citas: list[str]
    vectores: np.ndarray

    def por_cita(self) -> dict[str, np.ndarray]:
        return dict(zip(self.citas, self.vectores))


def precalcular(corpus: Corpus, embedder: Embedder, destino: Path | None = None) -> Path:
    """Embebe todo el corpus y lo guarda en `embeddings_<modelo>.npz`."""
    destino = destino or embedder.modelo.archivo_vectores()
    vectores = embedder.pasajes([f.texto_para_embeber() for f in corpus.fragmentos])
    np.savez_compressed(destino, citas=np.array([f.cita for f in corpus.fragmentos]), vectores=vectores,
                        modelo=np.array(embedder.modelo.clave), huella=np.array(corpus.huella()))
    return destino


def leer_vectores(ruta: Path) -> VectoresCorpus | None:
    if not ruta.exists():
        return None
    with np.load(ruta, allow_pickle=False) as z:
        return VectoresCorpus(str(z["modelo"]), str(z["huella"]), [str(c) for c in z["citas"]],
                              z["vectores"].astype(np.float32))
