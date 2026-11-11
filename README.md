# Planta de inyección PIA-3 · Sistema agéntico de Efrain Leon

TP de la Academia Novit 2026 (Desarrollo de Agentes IA y Software Agéntico). El sistema se conecta a la planta
simulada de Novit ([`NovitSoftware/academia2026-tp`](https://github.com/NovitSoftware/academia2026-tp)) y, en la
PC de planta y sin depender del enlace:

- convierte las **notas de voz** del operador en un parte con esquema fijo, se lo muestra en la tablet, pregunta
  cuando algo es ambiguo y entiende sus correcciones en lenguaje de campo;
- **detecta** en código si cada equipo está `SinNovedad` o hay que escalarlo, y vigila los desvíos sostenidos de los
  sensores;
- da la **alerta de seguridad** en segundos ante agua a presión, gas, humo o fuego, o una persona lesionada;
- deja lo escalado en una **cola hacia la nube** que se vacía en orden cuando vuelve el enlace;
- expone **tools de solo lectura** (equipos, sensores, órdenes, repuestos, tareas, manuales) también por **MCP**;
- indexa los manuales en **pgvector** con búsqueda híbrida, medida contra la línea de base de Novit.

Estado: **Entrega 1** (parte por voz, detección, tools y MCP, RAG medido). El análisis de la anomalía, las órdenes de
trabajo y su aprobación, el cierre y la certificación son de la Entrega 2.

## Cómo levantarlo

Requisitos: Docker con Compose. La planta se levanta primero porque crea las redes `planta-lan` y `planta-control`.

```bash
# 1. La planta simulada (en su repo)
git clone https://github.com/NovitSoftware/academia2026-tp && cd academia2026-tp
docker compose up -d --build

# 2. Este sistema (en este repo)
docker compose up -d --build
```

La primera construcción descarga los modelos y los deja **dentro de las imágenes**: Whisper `small` en la del sistema
y el LLM en la de Ollama. La red de planta no tiene internet y los volúmenes se pueden borrar entre corridas.

| Qué | Dónde |
| --- | --- |
| Visor de la planta (3D / 2D) | <http://localhost:8080> · <http://localhost:8081> (`?instructor` para el panel) |
| API de la planta | <http://localhost:8100/docs> |
| Logs del sistema | `docker compose logs -f sistema` |
| Servidor MCP | `http://herramientas:8001/mcp` dentro de `planta-lan` (no se publica fuera de Docker) |

Variables principales (todas con valor por defecto en `docker-compose.yml`): `LLM_MODELO` (`qwen3.5:2b`),
`STT_MODELO` (`whisper:small`), `TIMEOUT_NOTA_S`, `MAX_INTENTOS_BORRADOR`, `MAX_PASOS_LLM_POR_NOTA`,
`MAX_TOKENS_POR_NOTA`, `LLM_TIMEOUT_S`. Ver `src/sistema/config.py`.

## Qué corre en la planta y qué en la nube

| Servicio | Dónde | Por qué |
| --- | --- | --- |
| `sistema` (transcripción, parte, diálogo, detección, alerta) | PC de planta | El parte por voz, la detección y la alerta tienen que andar **sin enlace** (en `fuga-sin-enlace` el enlace se cae a los 10 min y la nota insegura llega con el enlace caído) |
| `ollama` (LLM local) | PC de planta | Respaldo de la extracción del parte: tiene que estar disponible sin enlace |
| `db` (PostgreSQL 16 + pgvector) | PC de planta | La memoria de cada nota, los partes, los eventos, la trazabilidad, la cola hacia la nube y el índice de manuales tienen que sobrevivir a un corte de enlace o de luz |
| `herramientas` (tools por MCP) | PC de planta | Consultan la API de la planta y los materiales, que están en la LAN |
| `nube` | Fuera de la planta | Recibe lo escalado. Solo se la alcanza por el proxy `enlace:3128`: cuando el enlace se cae, la planta acumula pendientes y los sincroniza en orden al volver. En la Entrega 2 corre acá el análisis de la anomalía |

Los servicios de planta van solo en `planta-lan`, con el label `academia.planta: pc` y límites que suman **4 CPU y
8 GB** (sistema 2 CPU / 2,5 GB, ollama 1,5 / 3,75 GB, db 0,25 / 0,75 GB, herramientas 0,25 / 0,75 GB). Salen a internet
por `HTTP(S)_PROXY=http://enlace:3128`. Además de `broker,sim,localhost`, `NO_PROXY` incluye los servicios propios de
la planta (`db,ollama,herramientas`): sin eso, el LLM local saldría por el enlace y dejaría de andar cuando se cae.

Todo usa **solo modelos locales en CPU** (pedido de Novit). Por qué cada uno: [INFORME.md](INFORME.md).

## Cómo funciona

```text
planta/recorridas ─► audio ─► Whisper small (local) ─► ¿condición insegura? ──sí──► aviso + AlertaSeguridad (< 30 s)
                                                     │
                                                     └─► números hablados → dígitos ─► reglas ──(si no alcanzan)──► LLM local
                                                                                         │      salida estructurada (Pydantic)
                                                                                         ▼
                                    TAG, unidad del manómetro, ambigüedades, rango histórico (código)
                                                                                         │
                     sistema/tablet ◄── borrador / pregunta ◄────────────────────────────┘
                     planta/respuestas ─► confirma / corrige ─► nuevo borrador
                                                     │ confirmado
                                                     ▼
                     sistema/eventos: SinNovedad / Escalado por equipo ─► cola hacia la nube (con parte, fotos, tendencia)
```

- **Specs (OpenSpec):** qué hace el sistema y por qué, un spec por capacidad con sus escenarios, en
  [openspec/specs/](openspec/project.md): transcripción, alerta de seguridad, extracción del parte, diálogo con la
  tablet, detección, latido y sincronización, control de ejecución, tools, búsqueda en manuales y evaluación. La mini
  spec del flujo del parte que pide la Entrega 1 son [extraccion-del-parte](openspec/specs/extraccion-del-parte/spec.md)
  y [dialogo-con-la-tablet](openspec/specs/dialogo-con-la-tablet/spec.md). Los cambios nuevos entran como changes de
  OpenSpec (`openspec/changes/`).
- **El modelo propone, el código dispone:** límites, conversiones, nombres de equipos, rangos y la decisión
  `SinNovedad`/`Escalado` son código determinístico. El texto de la nota entra delimitado como dato.
- **Reglas primero, LLM de respaldo:** el dictado del operador es regular y las reglas lo resuelven en milisegundos.
  El LLM local en CPU tarda 40 a 80 s por nota (`evaluacion/llm/`), así que entra solo cuando las reglas no explican
  todos los números de la nota, con un timeout. Si no llega a tiempo, sale el borrador parcial y el operador corrige.
- **Seguridad:** `src/sistema/procesamiento/seguridad.py`, reglas explícitas S1–S4 (sin LLM), probadas contra falsas
  alarmas ("golpeteo" no es "se golpeó"; "chorrea por la empaquetadura" no es agua a presión).
- **Detección:** `src/sistema/dominio/deteccion.py`. Por parte confirmado, un evento por equipo; por sensores, solo
  los desvíos sostenidos 30 min de planta (una bomba parada no es un desvío).
- **Control** (módulo 1.4): timeout global por nota, presupuesto de pasos y tokens de LLM, tope de borradores; cada
  paso y cada decisión (seguridad, `SinNovedad`/`Escalado`, consultas a la planta) quedan registrados con modelo,
  herramienta, argumentos, tokens, costo y tiempo (tabla `pasos`). El consumo por modelo se publica en
  `sistema/metricas` y lo muestra el visor (ver [Modelos y fluidez en vivo](#modelos-y-fluidez-en-vivo)).
- **Memoria:** el estado de la conversación de cada nota se guarda en Postgres en cada transición; política escrita
  en [docs/memoria.md](docs/memoria.md).

## Tools y MCP

Seis tools de solo lectura con contratos Pydantic estrictos (`extra="forbid"`), validación en capas, errores
estructurados `{codigo, mensaje, reintentable}`, timeouts y reintentos con backoff ante fallas transitorias
(`src/sistema/herramientas/`):

| Tool | Qué devuelve |
| --- | --- |
| `consultar_equipos` | Equipos, nombres informales, unidad del manómetro, sensores con límites de alarma |
| `consultar_historial_sensor` | Resumen y serie acotada del historiador (45 días) |
| `consultar_historial_ordenes` | Órdenes de trabajo del equipo |
| `consultar_repuestos` | Lista de materiales, stock por almacén y costo |
| `consultar_tareas` | Catálogo de tareas estándar y no estándar con costo y si detienen el equipo |
| `buscar_en_manuales` | Secciones de los manuales e historial con su cita (RAG) |

Se usan desde LangChain (`StructuredTool`) y se publican por un **servidor MCP** (SDK oficial, Streamable HTTP sin
estado, `python -m sistema.herramientas.servidor_mcp`, `:8001/mcp`) con las annotations `readOnlyHint` e
`idempotentHint`.

## RAG

Ver [docs/rag.md](docs/rag.md): fragmentos por sección con metadatos (equipo, fabricante, documento, sección, cita,
vigente), búsqueda híbrida en pgvector con filtros de vigencia y aplicabilidad, y la justificación de qué va por RAG y
qué por API o SQL (límites y stock nunca salen del RAG). Contra la línea de base BM25 de Novit (71 preguntas):

| | hit@5 | recall@5 | MRR | Rev. C en el top 5 |
| --- | ---: | ---: | ---: | ---: |
| BM25 de Novit | 0,845 | 0,664 | 0,573 | 42 preguntas |
| **Híbrida (multilingual-e5-small + léxica, con filtros)** | **0,859** | **0,742** | **0,718** | **0** |

Detalle y ablaciones en [evaluacion/rag/](evaluacion/rag/README.md).

## Modelos y fluidez en vivo

| Modelo | Para qué | Dónde corre |
| --- | --- | --- |
| Whisper small int8 (`faster-whisper`) | Transcribir cada nota | `sistema`, 2 hilos |
| Qwen3.5 2B (`qwen3.5:2b`, Ollama) | Respaldo de la extracción cuando las reglas no alcanzan | `ollama`, 2 hilos |
| multilingual-e5-small int8 (`fastembed`) | Embeddings de la búsqueda en manuales | `herramientas` |

Cómo se eligió cada uno y cuánto consume: [INFORME.md](INFORME.md).

- **Visor 2D de la planta** (<http://localhost:8081>): el panel de consumo muestra cada modelo del sistema con sus
  tokens de entrada y salida y la velocidad de generación. Se actualiza cada 10 s (`sistema/metricas`) y aparece
  desde el arranque, aunque el LLM todavía no haya hecho falta.
- **Reporte de funcionamiento**, de solo lectura sobre la base (anda sin enlace):

  ```bash
  docker compose exec sistema python -m sistema.metricas
  ```

Salida real al final de `fuga-sin-enlace` en el corrector de Novit, que arranca cada escenario con la base vacía:

```text
Sistema Efrain Leon · 4 notas (confirmada 3, alerta 1) · costo USD 0, todo local

Fluidez, en tiempo real
  Nota → primer mensaje en la tablet   p50 3,9 s · p95 4,6 s · máx 4,6 s · notas: 4
  Nota → alerta de seguridad           p50 4,6 s · p95 4,6 s · máx 4,6 s · alertas (límite 30 s): 1

Modelos y reglas
  faster-whisper small int8    4 notas · audio p50 8,8 s → transcribe en p50 3,6 s / p95 4,5 s (0,45× el audio) · 115 tokens a 7,6 tok/s
  reglas_parte                 3 notas · 3 completas (100,0 %) · p50 < 1 ms

Diálogo con el operador
  Confirmadas al primer borrador 2 de 3 (66,7 %) · preguntas 1 · borradores rehechos 0

Cola hacia la nube: 1 enviados · 0 pendientes
```

En `martes-tranquilo` la misma corrida dio 7 de 9 notas confirmadas al primer borrador, lo mismo que midió el
corrector (A2), y una demora a la tablet de p50 4,2 s / p95 12,0 s: las notas que llegan juntas esperan su turno de
transcripción. Cuando el LLM entra, el reporte suma su fila con llamadas, timeouts y tok/s de generación.

## Pruebas y evaluación

```bash
pip install -e ".[dev]"
pytest                                   # tests de reglas, diálogo, detección, seguridad y de cada tool (sin red)
```

| Suite | Qué mide | Dónde |
| --- | --- | --- |
| Transcripción | WER, números bien transcritos, latencia y RAM de cada modelo candidato, sobre las 102 notas del banco de voces con ruido de planta | [evaluacion/stt/](evaluacion/stt/) |
| LLM | Extracción del parte con el criterio del operador virtual | [evaluacion/llm/](evaluacion/llm/) |
| Reglas y detección | 400 notas generadas con el operador virtual de la planta: borrador confirmable, ambigüedades, decisión B1 | [evaluacion/reglas/](evaluacion/reglas/) |
| Parte por voz de punta a punta | Contra la verdad de campo (`/api/verdad` o una corrida del corrector): aciertos por campo, preguntas en ambiguas y de más, demoras, costo | [evaluacion/partes/](evaluacion/partes/README.md) |
| RAG | hit@k, recall@k, MRR, Rev. C antes que D, contra BM25 | [evaluacion/rag/](evaluacion/rag/README.md) |

Para correr un escenario y evaluarlo (con la planta en modo desarrollo), o evaluar una corrida del corrector:

```bash
python evaluacion/capturar_escenario.py martes-tranquilo --salida corridas --repo-planta ../academia2026-tp
python evaluacion/evaluar_partes.py
python evaluacion/evaluar_partes.py --corrida ../academia2026-tp/correccion/corridas/<corrida>/martes-tranquilo.json
```

El corrector de Novit también se puede correr localmente desde el repo de la planta:
`python correccion/corregir.py --repo ../efrain-leon --escenarios martes-tranquilo fuga-sin-enlace`.

**Resultado con el corrector de Novit** (clon limpio de este repo, `martes-tranquilo` + `fuga-sin-enlace`):
**91,3 / 100, aprueba, sin faltas eliminatorias**
([informe](evaluacion/corrector/informe-2026-11-10.md)). Todos los criterios medidos están en su máximo posible:
A2 y A3 no llegan al 100 % porque tres de las notas de esos escenarios no tienen ningún valor numérico (una nota de
seguridad y "la bomba está parada, en reserva"), y el corrector solo cuenta como borrador uno con valores. La alerta
de seguridad salió 4 s después de la nota, con el enlace caído; 0 mensajes inválidos.

La nota puede variar alrededor de un punto entre corridas: el audio de las notas cambia en cada corrida y Whisper a
veces transcribe distinto un número. En una corrida "mil seiscientos psi" salió "600 psi" (90,4 / 100): el borrador
avisó que estaba fuera del rango de los últimos 45 días, el operador lo corrigió y el parte final quedó bien.

## Estructura

```text
src/sistema/
  agente.py            orquestación de la PC de planta (MQTT, notas, tablet, eventos, latido, cola a la nube)
  config.py            configuración por variables de entorno
  metricas.py          consumo por modelo para el visor y reporte de funcionamiento
  dominio/             planta (equipos, nombres, límites) y detección
  procesamiento/       transcripción, seguridad, números, reglas del parte, extracción con LLM, diálogo
  llm/                 LLM local por LangChain, con presupuesto y registro de cada paso
  herramientas/        tools de solo lectura y servidor MCP
  rag/                 índice en pgvector y búsqueda híbrida
  persistencia/        PostgreSQL: notas, diálogo, partes, eventos, pasos, cola
  integraciones/       MQTT, API de la planta, enlace
  nube.py              el lado nube (recibe lo sincronizado)
ollama/                imagen del LLM local con el modelo adentro
datos/                 planta, materiales y corpus de manuales (de Novit)
openspec/              specs por capacidad (qué hace y por qué) y changes
docs/                  diseño: memoria, context builder, RAG
evaluacion/            suites de evaluación y resultados
tests/
```

## Limitaciones conocidas

- La primera lectura de un goteo de empaquetadura no lleva número (el operador no lo dicta) y la planta lo espera en
  gotas por minuto: ese primer borrador se corrige con la respuesta del operador.
- El LLM local en CPU es lento (40 a 80 s por nota); por eso es respaldo y no camino principal. Con la planta
  corriendo en la misma máquina suele cortar por timeout (45 s): el reporte de funcionamiento lo muestra.
- La limpieza periódica según la política de memoria y el análisis de anomalías llegan con la Entrega 2.
