# Evaluación del parte por voz contra la verdad de campo

Compara lo que el sistema mostró en la tablet con lo que el operador dijo de verdad (la verdad de campo de la planta),
nota por nota. Es la "primera evaluación contra `/api/verdad`" del anexo de la Entrega 1.

```bash
# Desde una corrida del corrector de Novit (trae la verdad y todo lo que publicó el sistema)
python evaluacion/evaluar_partes.py --corrida ../academia2026-tp/correccion/corridas/<corrida>/martes-tranquilo.json \
    --salida evaluacion/partes/martes-tranquilo.json

# O con la planta en desarrollo (/api/verdad abierta), después de correr un escenario
python evaluacion/evaluar_partes.py --salida evaluacion/partes/martes-tranquilo.json
```

## Resultados

Corrida del corrector del 11/11 con el código de la entrega (91,3 / 100):
[martes-tranquilo.json](martes-tranquilo.json) y [fuga-sin-enlace.json](fuga-sin-enlace.json), con el resumen y el
detalle de cada nota.

| | martes-tranquilo | fuga-sin-enlace |
| --- | ---: | ---: |
| Notas | 9 | 4 (1 de seguridad) |
| Con respuesta en la tablet | 9 / 9 | 4 / 4 |
| Aciertos del primer borrador: equipo | 18 / 18 | 4 / 4 |
| Aciertos del primer borrador: valor | 18 / 18 | 4 / 4 |
| Aciertos del primer borrador: unidad | 18 / 18 | 4 / 4 |
| Primer borrador confirmado | 8 / 9 | 2 / 3 |
| Preguntó en las notas ambiguas | 2 / 2 | 1 / 1 |
| Preguntó de más en las notas claras | 0 / 7 | 0 / 2 |
| Nota → primer mensaje en la tablet (p50 / p95) | 4,1 s / 4,6 s | 3,5 s / 3,5 s |
| Nota → alerta de seguridad | — | 3,5 s (límite 30 s) |
| Mensajes inválidos | 0 | 0 |
| Costo | USD 0 | USD 0 |

## Cómo leerlo

- **Aciertos por campo:** cada lectura con valor que dictó el operador se busca en el primer borrador con valores, por
  equipo y variable (y si no está, por valor parecido, para detectar un equipo equivocado). Valor y unidad se comparan
  con la tolerancia del operador virtual.
- **Primer borrador confirmado:** las notas que faltan son "la bomba está parada, en reserva": no tienen valores, así
  que el sistema no manda un borrador para confirmar sino un aviso ("Lo registro así") después de preguntar qué
  bomba es. El corrector las cuenta como no confirmadas en A2 y A3: es el techo de esos criterios. La nota de
  seguridad no entra en esta cuenta (no tiene parte); el corrector sí la cuenta en A2, por eso da 2 / 4 en
  `fuga-sin-enlace`. En `martes-tranquilo` da 8 / 9, igual que acá, y A4a y A4b marcan las mismas notas.
- **Preguntas:** una nota es ambigua si la verdad marca una ambigüedad ("la bomba" a secas, un diferencial dicho
  "dieciocho"). Un mensaje con opciones o sin filas cuenta como pregunta.
- **Demoras:** tiempo real desde que la planta publica la nota hasta el mensaje en la tablet o el `AlertaSeguridad`.
- **Costo:** todo corre local. Los tokens del LLM salen de `/api/estado` cuando se evalúa contra la planta en
  desarrollo; en estas corridas el LLM no hizo falta.
