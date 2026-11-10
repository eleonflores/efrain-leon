# LLM local para la PC de planta (CPU, sin GPU). El modelo se descarga al construir: queda dentro de la imagen.
FROM ollama/ollama:0.40.16

ENV OLLAMA_MODELS=/modelos OLLAMA_KEEP_ALIVE=24h OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 \
    OLLAMA_HOST=0.0.0.0:11434
ARG LLM_MODELO=qwen3.5:2b
RUN (ollama serve > /tmp/ollama.log 2>&1 &) && sleep 5 && ollama pull ${LLM_MODELO} && ollama list
