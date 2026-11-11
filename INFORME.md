# Informe técnico · Modelos

> Qué modelo resuelve cada tarea, con qué versión, en qué hardware se probó, cuánto consume y por qué se eligió.
> Novit pidió **solo modelos locales**: no hay modelos en la nube ni costo por token. Todo corre en CPU, dentro de los
> límites de la PC de planta (4 CPU y 8 GB para todos los servicios, sin GPU).

## Hardware de las pruebas

| | |
| --- | --- |
| Equipo | Notebook Dell Vostro 14 5410 (PC de trabajo) |
| CPU | Intel Core i5-11300H, 4 núcleos / 8 hilos, 3,1 GHz |
| RAM | 24 GB |
| GPU | Intel Iris Xe integrada (no se usa); sin GPU dedicada |
| Sistema | Windows 11 Pro, Docker Desktop 29.8.2 (WSL2), Compose v5.6.0 |
| Límites por contenedor | sistema 2 CPU / 2,5 GB · ollama 1,5 CPU / 3,75 GB · db 0,25 / 0,75 GB · herramientas 0,25 / 0,75 GB |

Las mediciones se hicieron con los mismos límites de CPU que en producción (`--cpus=2` para la transcripción y el
LLM) y con la planta simulada corriendo en la misma máquina, así que son conservadoras.

## Modelos por tarea

| Tarea | Modelo | Proveedor | Versión | Parámetros | Dónde corre |
| --- | --- | --- | --- | --- | --- |
| Transcripción de notas de voz | **Whisper small**, conversión CTranslate2 (`Systran/faster-whisper-small`), int8 | OpenAI (modelo), SYSTRAN (faster-whisper) | faster-whisper 1.2.1, CTranslate2 4.8.5 | 244 M | `sistema`, 2 hilos |
| Extracción del parte (respaldo de las reglas) | **Qwen3.5 2B** (`qwen3.5:2b` de Ollama) | Alibaba Cloud · Qwen | Ollama 0.40.16, imagen `ollama/ollama:0.40.16` | 2 B (2,7 GB en disco) | `ollama`, 2 hilos |
| Embeddings para el RAG | **multilingual-e5-small** (`intfloat/multilingual-e5-small`, ONNX int8 de `Xenova/multilingual-e5-small`) | Microsoft (intfloat) | fastembed 0.9.1, onnxruntime 1.31.1 | 118 M, 384 dim. | `herramientas` (consultas); el corpus viene precalculado |
| Detección de condiciones inseguras | Ninguno: reglas (`procesamiento/seguridad.py`) | — | — | — | `sistema` |
| Detección SinNovedad / Escalado | Ninguno: código determinístico (`dominio/deteccion.py`) | — | — | — | `sistema` |
| Comprensión de las respuestas del operador | Reglas para las formas conocidas | — | — | — | `sistema` |

Integración: LangChain (`langchain-core` 1.7.7, `langchain-ollama` 1.1.0) con salida estructurada por JSON Schema
validada con Pydantic 2.14.

## Transcripción: cómo se eligió

Banco de 102 notas del operador (voces de `datos/voces/` de la planta) con el mismo ruido de planta que agrega el
simulador, 2 CPU por modelo ([evaluacion/stt/](evaluacion/stt/)):

| Modelo | Error por palabra | Notas con todos los números bien | Latencia p50 / p95 por nota | RAM pico |
| --- | ---: | ---: | ---: | ---: |
| **Whisper small int8 + prompt de la planta (producción)** | **1,2 %** | **97 %** | 3,7 s / 6,3 s | 0,9 GB |
| Whisper small int8, prompt inicial | 6,5 % | 98 % | 3,6 s / 5,8 s | 1,15 GB |
| Parakeet TDT 0.6B v3 int8 (NVIDIA, ONNX local) | 7,6 % | 54 % | 1,9 s / 3,7 s | 1,8 GB |
| Whisper large-v3-turbo int8 | — | — | > 20 s por nota (medición cortada) | — |

El prompt de producción le da a Whisper el vocabulario y la forma de dictar de la planta ("La dos está en mil
seiscientos psi de descarga. El filtro B me dio uno ocho de diferencial."): el error por palabra bajó de 6,5 % a 1,2 %.

Whisper small es el que mejor transcribe lo que puntúa (números, equipos, unidades) y entra holgado en los 30 s que
tiene la alerta de seguridad: en la corrida final del corrector, en `fuga-sin-enlace`, la alerta salió 4,0 s
después de la nota, con el enlace caído y el audio bajado, transcripto y evaluado. Parakeet es más rápido pero a veces cambia de idioma a mitad de nota ("The 1 is in 115
kilograms") y junta los diferenciales ("uno dos" → 12). Turbo es más preciso en general pero tarda más de lo que la
alerta puede esperar en 2 CPU.

Consumo: la transcripción no usa tokens; ~3,6 s de CPU por nota de 10 s de audio.

## Embeddings: cómo se eligió

Tres modelos multilingües chicos en CPU, medidos con la suite de 71 preguntas de Novit y su evaluador, dentro de la
búsqueda híbrida (semántica + léxica con filtros de vigencia) ([evaluacion/rag/](evaluacion/rag/README.md)):

| Modelo | hit@5 | recall@5 | MRR | RAM del modelo | Consulta |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 de Novit (línea de base, sin modelo) | 0,845 | 0,664 | 0,573 | — | — |
| **multilingual-e5-small int8** | **0,859** | **0,742** | **0,718** | ~420 MB | 5 ms (43 ms la búsqueda completa) |
| jina-embeddings-v2-base-es int8 | 0,831 | 0,709 | 0,674 | mayor (768 dim.) | más lenta |
| paraphrase-multilingual-MiniLM-L12-v2 | 0,817 | 0,667 | 0,661 | ~570 MB | — |

e5-small es el mejor en las tres métricas, el más chico y el más rápido. Los vectores de los 701 fragmentos se
calculan una vez y viajan en el repo; en runtime el modelo solo embebe la consulta. Consumo: sin tokens de LLM.

## LLM: cómo se eligió y por qué es respaldo

Candidatos de los ejemplos de clase de Novit (Ollama, con soporte de salida estructurada):

| Modelo | Tamaño | Resultado |
| --- | ---: | --- |
| **qwen3.5:2b** | 2,7 GB | 33 % de partes correctos en 12 notas reales; latencia mediana 79 s, la mitad superó el timeout de 90 s ([evaluacion/llm/](evaluacion/llm/)) |
| ministral-3:3b | 3,0 GB | No se completó la medición: es más grande y más lento que qwen3.5:2b en CPU |
| gemma4:e2b | 4,6 GB | Descartado por memoria: no entra en los 4 GB del contenedor de Ollama |

Con 2 CPU el LLM procesa la entrada a 13–26 tokens/s y genera a 3,5–4,3 tokens/s: 40 a 80 s por nota. En la
corrección eso deja las últimas notas sin borrador. Por eso la extracción del parte va **primero por reglas**: el
dictado del operador es regular, y las reglas resuelven en milisegundos el 100 % de 400 notas generadas por el
operador virtual de la planta, con 95,5 % de primeros borradores confirmables, 32/32 ambigüedades detectadas y ninguna
pregunta de más ([evaluacion/reglas/](evaluacion/reglas/)). El LLM entra solo cuando las reglas no explican todos los
números de la nota (habla libre, una nota en vivo), con un timeout de 45 s; si no llega, sale el borrador parcial de
las reglas y el operador lo corrige.

Se eligió `qwen3.5:2b` como respaldo por ser el más chico de los candidatos con salida estructurada que entra en el
presupuesto de memoria, y porque el prefijo de instrucciones (~830 tokens) queda en la caché de Ollama entre notas.

### Tokens por tarea

| Tarea | Tokens de entrada | Tokens de salida | Costo |
| --- | ---: | ---: | ---: |
| Extracción del parte por reglas (camino normal) | 0 | 0 | USD 0 |
| Extracción con LLM (respaldo, por nota) | ~430 nuevos (+ ~830 en caché) | ~50 | USD 0 (local) |
| Transcripción | — (audio) | ~3–4 por segundo de audio (texto decodificado) | USD 0 |
| Respuestas del operador, seguridad, detección | 0 | 0 | USD 0 |

En las corridas de `martes-tranquilo` y `fuga-sin-enlace` el LLM no hizo falta: todas las notas las resolvieron las
reglas. El consumo real queda registrado por paso en la tabla `pasos`, con el tiempo de generación que informa Ollama,
y se publica cada 10 s en `sistema/metricas`: el visor 2D de la planta muestra una fila por modelo (Whisper y el LLM)
con sus tokens y la velocidad de generación. `python -m sistema.metricas` da el reporte de funcionamiento (ver
[README](README.md#modelos-y-fluidez-en-vivo)).

En vivo, con la planta corriendo en la misma máquina, Whisper transcribe en ~0,5× la duración del audio (~9,5 tokens
de texto por segundo, encoder incluido) y el LLM genera a ~4,8 tokens/s. En la demo del 10/11 las tres llamadas de
respaldo al LLM cortaron por timeout (45 s): con este hardware el respaldo rara vez llega a tiempo, y el camino que
sostiene la nota son las reglas.

## Conclusión

Con 4 CPU y sin GPU, lo que manda es la latencia: la alerta tiene 30 s y la planta no espera a un sistema lento.
Por eso:

- **Whisper small** para transcribir: el mejor en números y nombres de equipos de los que entran en el tiempo.
- **Reglas y código** para todo lo que tiene que ser determinístico (seguridad, detección, unidades, límites) y para
  el dictado típico.
- **Un LLM chico (Qwen3.5 2B)** de respaldo para lo que las reglas no cubren, con timeout y salida estructurada
  validada.
- **Nada en la nube**: todo funciona sin enlace, como pide el enunciado para el parte, la detección y la alerta.

Para la Entrega 2 (análisis de anomalías con RAG y fotos) el costo de un LLM en CPU vuelve a ser el límite: el
análisis no es urgente como la alerta, así que puede correr en segundo plano y en cola.
