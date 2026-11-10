# busqueda-en-manuales Specification

## Purpose

Encontrar en los manuales, el contrato y el historial de órdenes los fragmentos que responden una pregunta, con su
cita, sin devolver nunca lo vencido (la Rev. C del TX-350) ni lo que no aplica a PIA-3. El diseño completo y las
ablaciones están en `docs/rag.md` y `evaluacion/rag/`.

## Requirements

### Requirement: El RAG es para texto; los números salen de su fuente

`buscar_en_manuales` SHALL usarse para explicaciones, procedimientos, causas probables, fallas, contrato y lo escrito
en las órdenes. Los límites, el stock, los costos y las lecturas SHALL consultarse con las tools de su fuente
estructurada. La descripción de la tool SHALL decirlo, y la salida SHALL recordarlo cuando la pregunta suena a límite o
stock.

**Razón:** un número del RAG puede ser el de un documento viejo (la Rev. C dice alarma de vibración 4,5 mm/s; la hoja
de datos vigente, 7,1) y no habría cómo saberlo.

#### Scenario: Pregunta por un límite
- **WHEN** se pregunta "¿cuál es la alarma de vibración de la uno?"
- **THEN** la salida trae los fragmentos y una observación que remite a `consultar_equipos` para el valor

### Requirement: Lo vencido y lo que no aplica se filtran antes del ranking

Cada búsqueda SHALL filtrar `vigente` y `aplica_pia3` dentro de la consulta, antes de su `LIMIT`. La tool SHALL NOT
tener un argumento para pedir documentos vencidos.

**Razón:** filtrar después del top-k deja menos de k resultados y deja que la Rev. C desplace a lo vigente. Sin los
filtros la Rev. C aparece en el top 5 de 36 de las 71 preguntas de la suite; con ellos, en ninguna.

#### Scenario: Pregunta que la Rev. C responde distinto
- **WHEN** se pregunta por un límite que cambió entre la Rev. C y la Rev. D
- **THEN** ningún fragmento devuelto es de la Rev. C

### Requirement: Búsqueda híbrida

La búsqueda SHALL combinar tres listas de 50 candidatos: semántica (`multilingual-e5-small` int8, coseno en HNSW),
léxica (BM25 sobre `tsvector` con configuración `es_planta` = `spanish` + `unaccent`) y códigos exactos (`OT-25-0026`,
`TX-T07`, con más peso si están en el título; sin los que aparecen en más de 15 fragmentos). La fusión SHALL ser una
combinación convexa: cada lista normalizada min-max dentro de la consulta y sumada con su peso (semántica 0,4,
léxica 0,6, códigos 0,2). La consulta SHALL expandirse con la equivalencia de fallas del MBP-4 §6.1 (`TX-T07` ↔
`F09`) y los nombres de los equipos ("la dos" → `B-102 B2 bomba 2`).

**Razón:** medida con la suite de Novit (71 preguntas), la híbrida da hit@5 0,859, recall@5 0,742 y MRR 0,718,
contra 0,845, 0,664 y 0,573 del BM25 de Novit, y supera a la semántica sola (0,817 / 0,667 / 0,631) y a la léxica sola
(0,817 / 0,669 / 0,676). Con RRF (k = 60) la híbrida quedó en hit@5 0,803, debajo de BM25: la combinación convexa
conserva cuánto mejor es el primero que el segundo, y es estable con peso semántico entre 0,2 y 0,5. Sin reranker:
un cross-encoder costaría unos 30 ms por candidato en una CPU ocupada.

#### Scenario: Síntoma dicho en lenguaje de campo
- **WHEN** se pregunta "la bomba suena como si tuviera piedras adentro"
- **THEN** entre los primeros fragmentos está el de cavitación

#### Scenario: Código del fabricante
- **WHEN** se pregunta por `TX-T07`
- **THEN** también se encuentran los fragmentos de la falla F09

### Requirement: El índice se carga solo y sin internet

Los vectores de los 701 fragmentos SHALL ir precalculados en el repo y el modelo de embeddings en la imagen. Al
arrancar, el sistema y el servidor MCP SHALL asegurar el índice: si la base ya tiene ese corpus con ese modelo no hacen
nada; si no, lo cargan en una transacción con lock (pueden arrancar a la vez). Si faltan los vectores o el modelo, la
búsqueda SHALL seguir en modo léxico y decirlo en `modo`. Una falla del índice SHALL NOT frenar el parte por voz.

#### Scenario: Volúmenes borrados
- **WHEN** el corrector arranca un escenario con la base vacía
- **THEN** el índice queda cargado en segundos sin descargar nada

#### Scenario: Sin modelo de embeddings
- **WHEN** el modelo no está disponible
- **THEN** `buscar_en_manuales` responde con `modo: "lexica"`
