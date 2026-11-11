## Why

El enunciado define dos estados del parte: **Borrador** (armado desde las notas de voz, sin confirmar) y
**Confirmado** (el operador lo validó; recién entonces genera eventos). El anexo de la Entrega 1 pide que "el parte
pase de Borrador a Confirmado". Hoy la tabla `partes` recibe el parte recién cuando el operador confirma: el borrador
vive solo en la conversación de la nota (`notas.borrador`), así que en la base no se ve un parte en estado Borrador.

El corrector no lo mide (mide lo que llega a la tablet y los eventos), pero es el modelo de estados del enunciado.

## What Changes

- Cada borrador que sale a la tablet guarda el parte en `partes` como `Borrador`, con las filas que se muestran.
- Al confirmar, el mismo parte pasa a `Confirmado` con las filas finales y la hora de confirmación (como hoy).
- Un parte que llega al tope de borradores queda en `Borrador`. Las notas sin valores siguen yendo directo a
  `Confirmado`, porque no hay nada que confirmar.
- La política de memoria nombra los dos estados.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `dialogo-con-la-tablet`: el parte queda en `partes` como `Borrador` mientras se dialoga y pasa a `Confirmado` al
  confirmar.

## Impact

- `src/sistema/agente.py` (`avanzar`) y `docs/memoria.md`. Sin cambios de esquema: `partes.estado` ya existe.
- Servicio `sistema`: un `INSERT ... ON CONFLICT` por borrador. Sin impacto en CPU ni memoria.
- Entrega 1, sin cambio de criterios del corrector. Toca el flujo de la nota: se verifica A1–A4b y B1.
