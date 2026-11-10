# Evaluación del RAG

Mide la búsqueda en manuales e historial contra la suite de Novit (`datos/documentos/evaluacion/retrieval.json`, 71
preguntas) con su propio evaluador (`corpus.evaluar.evaluar` del repo de la planta) y la compara con su línea de base
BM25. Diseño del RAG en [docs/rag.md](../../docs/rag.md).

```bash
docker run -d --name rag-dev-db -e POSTGRES_USER=sistema -e POSTGRES_PASSWORD=sistema -e POSTGRES_DB=sistema \
    -p 5433:5432 pgvector/pgvector:0.8.1-pg16
python -m sistema.rag.indexar --precalcular --modelo e5-small-int8     # y minilm-l12, jina-es-int8 para comparar
DATABASE_URL=postgresql://sistema:sistema@localhost:5433/sistema python evaluacion/rag/evaluar_rag.py
```

Resultados completos (por tipo de pregunta y por configuración) en `resultados.json`.

## Modelos de embeddings comparados (CPU, 2 hilos, fastembed/ONNX)

| Modelo | Dim. | RAM del modelo | Consulta p50 | Híbrida hit@5 | Híbrida recall@5 | Híbrida MRR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **intfloat/multilingual-e5-small (int8)** | 384 | ~420 MB | 5 ms | **0,859** | **0,742** | **0,718** |
| jinaai/jina-embeddings-v2-base-es (int8) | 768 | mayor | más lenta | 0,831 | 0,709 | 0,674 |
| paraphrase-multilingual-MiniLM-L12-v2 | 384 | ~570 MB | — | 0,817 | 0,667 | 0,661 |

**Elegido: multilingual-e5-small int8**: el mejor en las tres métricas, el más chico y el más rápido.

## Configuraciones (e5-small-int8)

| Configuración | hit@5 | recall@5 | MRR | distractor@5 | Rev. C antes que D (top 5) | Rev. C en el top 5 | No aplica en el top 5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 de Novit | 0,845 | 0,664 | 0,573 | 0,099 | 39 | 42 | 4 |
| Solo vectores, sin filtros | 0,803 | 0,631 | 0,555 | 0,085 | 21 | 39 | 2 |
| Solo vectores | 0,817 | 0,667 | 0,631 | 0,000 | 0 | 0 | 0 |
| Solo léxica | 0,817 | 0,669 | 0,676 | 0,014 | 0 | 0 | 0 |
| Híbrida con RRF | 0,803 | 0,697 | 0,702 | 0,014 | 0 | 0 | 0 |
| Híbrida sin filtros | 0,845 | 0,704 | 0,637 | 0,099 | 20 | 36 | 7 |
| Híbrida sin expansión de códigos de falla | 0,845 | 0,728 | 0,711 | 0,014 | 0 | 0 | 0 |
| **Híbrida (combinación ponderada, con filtros y expansión)** | **0,859** | **0,742** | **0,718** | **0,014** | **0** | **0** | **0** |

- **Filtros de vigencia y aplicabilidad** (pre-filtering): sacan la Rev. C y las secciones de otros modelos o plantas
  antes del top-k. Sin ellos la Rev. C aparece antes que la D en 20 preguntas; con ellos, en ninguna.
- **Expansión de códigos de falla** (MBP-4 §6: `TX-T07` → `F09`): suma 1,4 puntos de hit@5.
- **Fusión ponderada** de las listas semántica y léxica (pesos 0,4 / 0,6) rinde más que RRF en esta suite.

Las preguntas que todavía fallan en el top 5 son sobre todo de límites y de operación con varias secciones
relevantes; los límites, de todos modos, no se responden por RAG sino con `consultar_equipos` (hoja de datos).
