## Why

Probando la demo en vivo, el operador corrigió "la uno estaba en ciento quince kilos, no en ciento cincuenta" y el
nuevo borrador mostró B-101 115 kg/cm² junto con "Ojo: la uno 150 kg/cm² está fuera del rango de los últimos 45
días". El aviso se calcula una sola vez, al armar el primer borrador, y una corrección no lo actualiza: el operador
lee un aviso sobre un valor que ya no está en el parte.

No mueve puntos del corrector (el operador virtual compara TAG, valor y unidad, no el texto), pero es lo primero que
ve una persona que corrige un valor raro.

## What Changes

- Una corrección del operador (valor, unidad o equipo de una fila) borra el aviso de rango de esa fila.
- Después de aplicar las correcciones, el sistema recalcula el rango histórico de las filas: si el valor corregido
  sigue fuera, el aviso vuelve con el valor nuevo; si está dentro, no hay aviso.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `deteccion-en-planta`: el aviso de rango histórico se recalcula después de cada corrección del operador.

## Impact

- `src/sistema/procesamiento/dialogo.py` (`aplicar`) y `src/sistema/agente.py` (`procesar_respuesta`).
- Servicio `sistema`. Sin costo de CPU ni memoria: el rango está en caché (se recalcula cada 6 h de planta).
- Entrega 1, sin cambio de criterios del corrector.
