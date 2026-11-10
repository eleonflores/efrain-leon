# RAG de los manuales y el historial (Entrega 1)

> Qué se indexa, cómo se busca, cómo se filtra la Rev. C y lo que no aplica a PIA-3, qué se consulta por RAG y qué
> por API o SQL, y cuánto rinde contra la línea de base BM25 de Novit. Código en `src/sistema/rag/`, tool
> `buscar_en_manuales` en `src/sistema/herramientas/manuales.py`, medición en `evaluacion/rag/`.

## Qué va por RAG y qué no

El RAG es para **texto**: explicaciones, procedimientos, causas probables, el catálogo de fallas, el contrato y lo
que la gente escribió en las órdenes. Un **número operativo** (un límite, un stock, una lectura) tiene una fuente de
verdad estructurada y se consulta ahí: si saliera del RAG podría ser el de un documento viejo (la Rev. C dice alarma
de vibración 4,5 mm/s; la hoja de datos vigente, 7,1) y no habría cómo saberlo.

| Pregunta | Fuente | Tool |
| --- | --- | --- |
| Límites de alarma y disparo, equipos, nombres de campo, unidades | `GET /api/planta` (hoja de datos = Rev. D y MBP-4) | `consultar_equipos` |
| Valores medidos, tendencias | Historiador de la planta | `consultar_historial_sensor` |
| Stock, costo de repuestos, listas de materiales | Materiales (`materiales.yaml`, SQL) | `consultar_repuestos` |
| Tareas del plan: horas, detención, repuestos, costo | Catálogo de tareas (materiales) | `consultar_tareas` |
| Órdenes por equipo, fecha o tarea (campos) | `GET /api/historial-ordenes` | `consultar_historial_ordenes` |
| Causa probable por síntomas, procedimientos, seguridad, roles y reglas de aprobación | Manuales (TX350-D, FC48-3, MBP-4) | **`buscar_en_manuales`** |
| Traducir un código del fabricante (`TX-T07`) al catálogo (F09) | MBP-4 §6.1 | **`buscar_en_manuales`** |
| Qué se encontró antes en un equipo (texto libre de campo) | Historial de órdenes | **`buscar_en_manuales`** |
| Precios del contrato, cálculo del habilita, diferencias de certificación | CT-SVP-2025, CERT-EJ | **`buscar_en_manuales`** |

La descripción de la tool se lo dice al modelo ("No la uses para límites de alarma o disparo…, stock o costo de
repuestos…") y la salida lo recuerda en `observacion` cuando la pregunta suena a límite o a stock. Las dos tools se
complementan: el número sale de `consultar_equipos` y la explicación con su cita, del manual.

## Corpus y fragmentos

Se indexa `datos/documentos/fragmentos.jsonl` de Novit (copiado al repo con `indice.json` y la suite, porque la imagen
se construye sin acceso a la planta): **701 fragmentos**, una sección por línea de cada documento (TX350-D 112,
TX350-C 108, FC48-3 98, MBP-4 109, CT-SVP-2025 17, CERT-EJ 14) y una por orden de trabajo (243).

**Chunking: las secciones de Novit, tal cual.** Respetan la estructura del manual (criterio estructural del módulo
2.2), cada una se entiende sola, traen su cita (`TX350-D §3.2`) y son cortas: mediana 236 caracteres, máximo 2.709,
ninguna pasa los 512 tokens del modelo. Partirlas más agregaría fragmentos sin contexto y obligaría a reagrupar citas;
juntarlas haría embeddings difusos y citas imprecisas. Dos agregados:

- **Contexto en el embedding** (chunking contextual): cada sección se embebe con una línea que la sitúa,
  `Bomba alternativa triplex Trimax TX-350 (TX350-D, revisión D). 3.2 Límites de operación…`.
- **Texto de búsqueda de las órdenes** (`texto_busqueda`): el texto libre de campo tiene abreviaturas y equipos
  dichos de mil formas. Para buscar (no para mostrar) se reescribe la cabecera en palabras (equipo con su nombre de
  campo del MBP-4 §2.2, tarea con su nombre del MBP-4 §13) y se expanden las abreviaturas de la planilla (MBP-4 §4.4)
  y de campo (`cbio`, `dif`, `empaq`, `lts`, `c/`, `x`). La orden se muestra y se cita con su texto original.

## Metadatos (tabla `rag_fragmentos`)

| Columna | De dónde sale | Para qué |
| --- | --- | --- |
| `cita` | `id` de Novit: `TX350-D §3.2`, `historial OT-25-0026` | Citar; es lo que espera la suite |
| `documento`, `revision`, `tipo_documento`, `titulo_documento` | `indice.json` | Filtrar por documento; mostrar la revisión |
| `fabricante` | `emisor` de `indice.json` (Trimax, Filtrapat, la operadora) | Mostrar de quién es el dato |
| `equipos` | `equipos` del documento; en una orden, su equipo | Filtrar por equipo (`'PLANTA'` cuenta para todos) |
| `seccion`, `titulo`, `pagina`, `fecha` | `fragmentos.jsonl`; la fecha de la cabecera de la orden | Citar con página; acotar órdenes |
| `vigente` | `indice.json` / `fragmentos.jsonl` (la Rev. C es `false`) | **Filtro previo** |
| `aplica_pia3`, `motivo_no_aplica` | Regla por `clave` de la sección o de su capítulo (ver abajo) | **Filtro previo** |
| `codigos`, `codigos_titulo` | Códigos extraídos del texto y del título | Lista de códigos exactos |
| `texto`, `texto_busqueda` | El texto original y el de búsqueda | Mostrar / indexar |
| `tsv` | `to_tsvector('es_planta', texto_busqueda)`, columna generada | Búsqueda léxica (GIN) |
| `embedding` | `vector(384)`, precalculado en la imagen | Búsqueda semántica (HNSW coseno) |

`rag_lexemas` guarda el `ndoc` de cada lexema (`ts_stat`) para el IDF de BM25; `rag_meta` guarda qué versión del
índice está cargada (esquema, modelo y huella del corpus).

**Qué no aplica a PIA-3** (50 fragmentos, todos con un "no aplica" o "solo como referencia" en su texto): la familia
de modelos (`TX350-D §2.1`, `FC48-3 §2.1`: TX-250, TX-500, FC-24, FC-96), los límites de otros modelos
(`TX350-D §3.3`) y de otras plantas (`MBP-4 §5.3`), las secciones de PIA-1 y PIA-2 (`MBP-4 §17`), instalación
(`TX350-D §4`, `FC48-3 §5`), preservación (`TX350-D §11`), transporte (`FC48-3 §11`) y opcionales (`TX350-D §12`,
`FC48-3 §16`). La regla usa la `clave` que el generador de Novit le pone a cada sección y se hereda del capítulo; los
tests verifican que ninguna de las secciones relevantes de las 71 preguntas quede afuera. Los precios del contrato
anterior (`CT-SVP-2025 §2.5`) **sí** aplican: valen para certificar trabajos de 2024.

## Búsqueda híbrida

```
pregunta ─┬─ embedding (e5-small, "query: …") ─── sem: coseno <=> (HNSW)                ─┐
          ├─ + expansión (fallas, equipos) ────── lex: BM25 sobre tsvector (GIN)        ─┼─ RRF ─ top k ─ citas
          └─ códigos exactos (+ MBP-4 §6.1) ───── cod: códigos raros, x2 si en el título ─┘
             cada lista: WHERE vigente AND aplica_pia3 AND <filtros>  (antes del LIMIT)
```

- **Filtro previo, no posterior.** El `WHERE` de vigencia y aplicabilidad está dentro de cada una de las tres
  búsquedas, antes de su `LIMIT` (módulo 2.2: filtrar después del top-k deja menos de k resultados y deja que la
  Rev. C desplace a lo vigente del ranking). En el HNSW, `hnsw.iterative_scan = strict_order` hace que el filtro no
  acorte la lista. Lo pone el sistema: la tool no tiene un argumento para pedir la Rev. C.
- **sem**: `multilingual-e5-small` int8 con los prefijos `query:`/`passage:` del modelo. Encuentra por significado
  ("ruido a piedras" → cavitación).
- **lex**: full-text de Postgres con una configuración `es_planta` = `spanish` + `unaccent` (el historial está sin
  tildes y `spanish` sola no une "cigüeñal" con "cigueñal"). La consulta es un OR de los lexemas de la pregunta (el
  AND de `plainto_tsquery` no encuentra casi nada con preguntas en lenguaje natural) y el puntaje es **BM25 en SQL**
  con el IDF de `rag_lexemas`: `ts_rank` no tiene IDF y "bomba" pesaría como "cavitación".
- **cod**: el stemming parte los códigos (`OT-25-0026` → `ot`, `-25`, `-0026`; `B-101` → `b`, `-101`), así que se
  extraen con una expresión regular (la misma al indexar y al consultar) y se buscan exactos en un `text[]` con GIN.
  Pesan por rareza y el doble si el código está en el título de la sección. No entran los códigos que aparecen en
  más de 15 fragmentos ni los nombres de equipos y modelos (`B-101`, `TX-350`, `PIA-3`): no discriminan.
- **Expansión de la consulta.** Fallas: si la pregunta trae `TX-T07`, se agrega `F09` (y al revés), con la tabla del
  MBP-4 §6.1 (un test verifica que coincide con la del corpus). Equipos: "la dos" agrega `B-102 B2 bomba 2`, que es
  como aparece en las órdenes.
- **RRF**: `Σ peso / (k + posición)` sobre las tres listas (50 candidatos cada una). Combina posiciones, no puntajes,
  así no hay que calibrar distancias coseno contra BM25.

Sin reranker: un cross-encoder multilingüe chico (mMiniLM, ~120 M parámetros) costaría una inferencia por candidato
(20 × ~30 ms) en una CPU que ya está ocupada con el LLM y la transcripción.

<!-- RESULTADOS -->

## Carga al arrancar

El corrector borra los volúmenes entre escenarios y la red de planta no tiene internet:

1. **Al construir la imagen**, `python -m sistema.rag.indexar --precalcular` descarga el modelo al cache de fastembed
   (`FASTEMBED_CACHE_PATH`) y deja `datos/documentos/embeddings_e5-small-int8.npz` (citas, vectores, modelo y huella
   del corpus).
2. **Al arrancar**, `await asegurar_indice(conexion)` mira `rag_meta`: si la base ya tiene este corpus con este
   modelo no hace nada; si no, en una transacción con `pg_advisory_xact_lock` (el sistema y el servidor MCP pueden
   arrancar a la vez) crea la configuración de texto, la tabla, copia las 701 filas con `COPY`, calcula las
   estadísticas léxicas y **después** crea los índices HNSW y GIN. Tarda alrededor de un segundo.
3. El buscador también llama a `asegurar_indice` en su primera conexión: si el servidor MCP arranca antes que el
   sistema, carga él.

Si faltan los vectores precalculados (o son de otro corpus), se calculan en el momento; si tampoco está el modelo, se
carga sin vectores y la búsqueda sigue solo léxica (`modo: "lexica"` en la salida de la tool).

## Configuración

| Variable | Defecto | Qué es |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://sistema:sistema@db:5432/sistema` | La base (la misma del sistema) |
| `RAG_MODELO` | `e5-small-int8` | Modelo de embeddings (`minilm-l12` y `jina-es-int8` quedan para comparar) |
| `RAG_HILOS` | `2` | Hilos de onnxruntime |
| `FASTEMBED_CACHE_PATH` | `$HF_HOME/../fastembed` | Dónde está el modelo (en la imagen, `/modelos/fastembed`) |
| `DOCUMENTOS_PATH` | `datos/documentos` del repo o `/app/datos/documentos` | Corpus y vectores precalculados |
