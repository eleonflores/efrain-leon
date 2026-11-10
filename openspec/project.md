# Contexto del proyecto — Planta de inyección PIA-3

## Propósito

Sistema agéntico de la **PC de planta** para la planta de inyección de agua PIA-3, trabajo integrador de la
Academia Novit 2026. Corre junto a la planta simulada de Novit
([`NovitSoftware/academia2026-tp`](https://github.com/NovitSoftware/academia2026-tp)) y, sin depender del enlace:

1. Transcribe las **notas de voz** del operador y arma el **parte de recorrida**.
2. Se lo muestra en la **tablet**, pregunta lo ambiguo y entiende las correcciones en lenguaje de campo.
3. Decide en código si cada equipo está `SinNovedad` o hay que **escalarlo**, y vigila los desvíos de los sensores.
4. Da la **alerta de seguridad** en segundos.
5. Deja lo escalado en una **cola hacia la nube** que se vacía en orden cuando vuelve el enlace.
6. Expone **tools de solo lectura** (también por **MCP**) y un **RAG** sobre los manuales.

## Entregas

| Entrega | Alcance | Escenarios del corrector | Estado |
|---|---|---|---|
| **1** | Parte por voz, detección, alerta, latido y cola, tools y MCP, RAG medido | `martes-tranquilo`, `fuga-sin-enlace` | Entregada: 91,3/100 |
| **2** | Análisis de la anomalía con RAG y fotos, orden de trabajo, aprobación, cierre y certificación | `tormenta-perfecta`, `sin-luz`, `contratista`, `ataque` | Sin publicar |

## Capacidades (specs)

| Spec | Qué cubre |
|---|---|
| [`transcripcion`](specs/transcripcion/spec.md) | Audio de la nota → texto, local y en CPU |
| [`alerta-de-seguridad`](specs/alerta-de-seguridad/spec.md) | Condiciones S1–S4, alerta y aviso en < 30 s sin enlace |
| [`extraccion-del-parte`](specs/extraccion-del-parte/spec.md) | Texto → filas del parte: números, reglas, LLM de respaldo, TAG, unidades, ambigüedades |
| [`dialogo-con-la-tablet`](specs/dialogo-con-la-tablet/spec.md) | Borrador, preguntas, correcciones, confirmación y estado que sobrevive a un reinicio |
| [`deteccion-en-planta`](specs/deteccion-en-planta/spec.md) | `SinNovedad`/`Escalado` por equipo, desvíos sostenidos, rango histórico |
| [`latido-y-sincronizacion`](specs/latido-y-sincronizacion/spec.md) | Latido, estado del enlace y cola hacia la nube |
| [`control-de-ejecucion`](specs/control-de-ejecucion/spec.md) | Timeout, presupuesto, registro de pasos, métricas y validación de lo publicado |
| [`herramientas-de-consulta`](specs/herramientas-de-consulta/spec.md) | Seis tools de solo lectura y el servidor MCP |
| [`busqueda-en-manuales`](specs/busqueda-en-manuales/spec.md) | RAG híbrido con filtros de vigencia y aplicabilidad |

El diseño que no es requisito vive en `docs/` (memoria, context builder, RAG) y la elección de modelos con sus
mediciones en `INFORME.md`.

## Stack

- **Python 3.11**, `asyncio`. MQTT con `aiomqtt`, HTTP con `httpx`, contratos con **Pydantic 2** y el paquete
  `planta_contrato` de Novit (instalado por pip desde un commit fijo).
- **Modelos, todos locales en CPU:** Whisper `small` int8 (faster-whisper) para transcribir, `qwen3.5:2b` en
  **Ollama** vía **LangChain** como respaldo de la extracción, `multilingual-e5-small` int8 (fastembed) para el RAG.
- **PostgreSQL 16 + pgvector** para el estado de las notas, los partes, los eventos, los pasos, la cola y el índice.
- **SDK `mcp`** (Streamable HTTP) para el servidor de tools.
- **Docker Compose**: `sistema`, `ollama`, `db`, `herramientas` en `planta-lan` (4 CPU y 8 GB en total) y `nube`
  detrás del proxy del enlace.

## Arquitectura

```
src/sistema/
  agente.py        orquestación: MQTT, notas, tablet, eventos, latido, cola a la nube
  dominio/         planta (equipos, nombres, límites) y detección — sin I/O
  procesamiento/   transcripción, seguridad, números, reglas del parte, diálogo — sin I/O salvo el modelo de voz
  llm/             LLM local con presupuesto y registro de cada paso
  herramientas/    tools de solo lectura y servidor MCP
  rag/             índice en pgvector y búsqueda híbrida
  persistencia/    PostgreSQL
  integraciones/   MQTT, API de la planta, enlace
  nube.py          el lado nube (recibe lo sincronizado)
```

`dominio/` y `procesamiento/` son funciones puras sobre datos: ahí está la lógica que se testea. `agente.py` solo
coordina.

## Convenciones

- **Comentarios:** el código va sin comentarios salvo una línea neutral cuando el nombre no alcanza. Nada de
  justificaciones, historia, mediciones ni números de tarea: eso va en el spec (**Razón:**) o en `docs/`.
- **Tests:** cada test prueba algo que vale la pena (una regla de negocio, un caso real que falló). Nada de defaults
  contra su literal ni comportamiento del framework; los casos parecidos van en un `parametrize`.
- **Idioma:** código, specs y documentación en español.
- **Cambios con OpenSpec:** `/opsx:propose` → `/opsx:apply` → `/opsx:archive`. Un cambio que toca el flujo de una
  nota se verifica con el corrector local de Novit antes de archivarse.

## Cómo se verifica

```bash
pytest                                                        # reglas, diálogo, detección, seguridad, tools, RAG
python correccion/corregir.py --repo ../efrain-leon \
       --escenarios martes-tranquilo fuga-sin-enlace          # desde el repo de la planta
```

Las suites de medición (transcripción, LLM, reglas, RAG, parte de punta a punta) están en `evaluacion/`.
