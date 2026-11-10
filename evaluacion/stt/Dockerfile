# Banco de prueba de modelos de transcripción. Se construye desde la raíz del repo:
#   docker build -f evaluacion/stt/Dockerfile -t efrain-leon-bench-stt .
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=/cache/hf

RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 && rm -rf /var/lib/apt/lists/*
RUN pip install faster-whisper "onnx-asr[cpu,hub]" soundfile jiwer numpy

WORKDIR /app
COPY src /app/src
COPY evaluacion/stt/bench_stt.py /app/bench_stt.py
ENV PYTHONPATH=/app/src:/planta_sim
ENTRYPOINT ["python", "/app/bench_stt.py"]
