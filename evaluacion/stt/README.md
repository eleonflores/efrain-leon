# Evaluación de transcripción (STT)

Compara modelos locales de transcripción sobre las notas de voz del operador, con el mismo ruido de planta que agrega
el simulador, y con los mismos límites de CPU que en producción.

- **Datos:** las 102 notas pregrabadas del banco de voces de la planta (`datos/voces/` del repo de Novit), cada una con
  su texto, mezcladas con `planta_sim.audio.ruido_planta` (intensidad 0,45–0,7, como hace el simulador).
- **Métricas:** error por palabra sobre texto normalizado (números en dígitos con `sistema.procesamiento.numeros`),
  notas con todos los números bien, recall de números, latencia por nota (p50/p95), factor de tiempo real y RAM pico.
- **Un modelo por contenedor**, así la RAM pico es solo la suya.

```bash
docker build -f evaluacion/stt/Dockerfile -t efrain-leon-bench-stt .
docker run --rm --cpus=2 --memory=4g -v stt-cache:/cache \
  -v <repo-planta>/datos/voces:/voces:ro -v <repo-planta>/planta/sim:/planta_sim:ro \
  -v $PWD/evaluacion/stt/resultados:/resultados \
  efrain-leon-bench-stt --hilos 2 --modelo whisper:small --salida /resultados/whisper-small.json
```

## Resultados (PC de trabajo: i5-11300H, 2 CPU por modelo)

| Modelo | Error por palabra | Notas con números bien | Recall de números | p50 / p95 | RAM |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Whisper small int8, prompt de producción** | **1,2 %** | 97,1 % | — | 3,7 s / 6,3 s | 0,9 GB |
| Whisper small int8 (faster-whisper), prompt inicial | 6,5 % | **98,0 %** | 99,5 % | 3,6 s / 5,8 s | 1,15 GB |
| Parakeet TDT 0.6B v3 int8 (onnx-asr) | 7,6 % | 53,9 % | 96,7 % | 1,9 s / 3,7 s | 1,8 GB |
| Whisper large-v3-turbo int8 | — | — | — | > 20 s por nota | — |

Las métricas de números se recalcularon con el normalizador final (que junta los diferenciales que la transcripción
parte: "uno, dos" → 1.2). Turbo se cortó a los 24 minutos sin completar 40 notas: más de 20 s por nota, incompatible
con los 30 s de la alerta. Parakeet, además de errar más números, a veces cambia al inglés a mitad de nota.

**Elegido: Whisper small int8**, con el prompt de vocabulario de la planta (`sistema.procesamiento.stt.PROMPT`).
Archivos con cada transcripción en `resultados/`.
