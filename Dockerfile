# Imagen del sistema (PC de planta, herramientas MCP y nube). Los modelos quedan dentro de la imagen: la red de planta
# no tiene internet y el corrector borra los volúmenes entre escenarios.
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=/modelos/hf
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# 1. Dependencias (se cachean mientras no cambie pyproject.toml).
COPY pyproject.toml ./
RUN mkdir -p src/sistema && touch src/sistema/__init__.py && pip install ".[stt,mcp,rag]" && rm -rf src

# 2. Modelo de transcripción (ver evaluacion/stt/: Whisper small int8 fue el mejor en números y entra en 30 s).
ARG STT_TAMANO=small
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${STT_TAMANO}', device='cpu', compute_type='int8')"

# 3. Código y datos (el corpus de manuales con sus embeddings ya precalculados: ver evaluacion/rag/).
COPY src ./src
COPY datos ./datos
RUN pip install --no-deps .

# 4. Modelo de embeddings del RAG (consultas en runtime; los vectores del corpus vienen precalculados).
ARG RAG_MODELO=e5-small-int8
ENV RAG_MODELO=${RAG_MODELO} FASTEMBED_CACHE_PATH=/modelos/fastembed
RUN python -c "from sistema.rag.embeddings import Embedder; print(len(Embedder(hilos=1).consulta('prueba')), 'dimensiones')"

ENV HF_HUB_OFFLINE=1 STT_MODELO=whisper:${STT_TAMANO} MATERIALES_PATH=/app/datos/materiales.yaml
CMD ["python", "-m", "sistema.agente"]
