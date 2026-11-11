# evaluacion Specification

## Purpose

Medir el sistema contra la verdad de campo de la planta, con los mismos datos que usa el corrector, y dejar en el repo
los resultados de los escenarios de cada entrega. Las otras suites (transcripción, LLM, reglas y RAG) tienen su
README en `evaluacion/`.

## Requirements
### Requirement: El parte se evalúa contra la verdad de campo

El repo SHALL tener una evaluación del parte por voz contra la verdad de campo de la planta (`/api/verdad` con la
planta en desarrollo, o la que guarda cada corrida del corrector) que reporte por escenario:

- aciertos por campo del primer borrador: equipo, valor y unidad;
- primeros borradores confirmados y partes confirmados al final;
- si preguntó en las notas con ambigüedad y si preguntó de más en las claras;
- la demora de la nota a la tablet (p50 y p95) y a la alerta de seguridad;
- los mensajes inválidos y el costo.

Los resultados de los escenarios de la entrega SHALL estar en `evaluacion/partes/`, generados con el código que se
entrega.

**Razón:** el anexo de la Entrega 1 pide una primera evaluación contra `/api/verdad` (aciertos por campo y si preguntó
solo en las notas ambiguas) y el enunciado, una suite que reporte aciertos, costo y latencia. `/api/verdad` está
cerrada durante la corrección, pero el corrector guarda la verdad en cada corrida: evaluar desde la corrida usa
exactamente los datos con los que se puntuó.

#### Scenario: Desde una corrida del corrector
- **WHEN** se corre `python evaluacion/evaluar_partes.py --corrida <escenario>.json --salida evaluacion/partes/<escenario>.json`
- **THEN** el resumen trae los aciertos por campo, las preguntas en ambiguas y de más, las demoras y el costo

#### Scenario: Con la planta en desarrollo
- **WHEN** la planta corre con `/api/verdad` abierta y se corre `python evaluacion/evaluar_partes.py`
- **THEN** la misma evaluación corre contra la API de la planta y suma el consumo de tokens del visor

