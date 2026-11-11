## Why

El anexo de la Entrega 1 pide una "primera evaluación contra `/api/verdad`: aciertos por campo, y si preguntó solo en
las notas que tenían ambigüedad", y el enunciado, una suite que reporte aciertos, costo y latencia. El script
`evaluacion/evaluar_partes.py` existe, pero sus resultados quedaron fuera del repo y son de una versión vieja del
sistema. Además, solo lee la API de la planta, que el corrector cierra durante la corrección.

## What Changes

- `evaluar_partes.py` acepta `--corrida`: el JSON de un escenario de una corrida del corrector, que trae la verdad de
  campo y el registro de lo que publicó el sistema. Así se evalúa con los mismos datos con los que se puntuó.
- El resumen suma el escenario y el costo (USD 0: todo es local).
- Cada lectura de la verdad se empareja primero con la fila del mismo equipo y variable: emparejar solo por valor
  cruzaba presiones de bombas distintas que, convertidas, dan casi lo mismo (1600 psi y 112 kg/cm²).
- Los resultados de `martes-tranquilo` y `fuga-sin-enlace`, generados con el código de la entrega, quedan en
  `evaluacion/partes/` con un README que los explica.
- Nuevo spec `evaluacion` con el requisito de la evaluación del parte.

## Capabilities

### New Capabilities

- `evaluacion`: cómo se mide el sistema contra la verdad de campo y qué resultados quedan en el repo.

### Modified Capabilities

Ninguna.

## Impact

- `evaluacion/evaluar_partes.py`, nuevo `evaluacion/partes/` y la tabla de suites del `README.md`.
- No toca ningún servicio de planta ni el flujo de una nota.
- Entrega 1, sin cambio de criterios del corrector.
