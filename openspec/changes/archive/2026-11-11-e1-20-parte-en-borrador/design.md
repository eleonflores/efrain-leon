## Context

`Base.guardar_parte(nota_id, estado, filas, ts)` hace un upsert por `nota_id` y pone `confirmado = now()` solo para
`Confirmado`. Hoy se llama dos veces: al confirmar un borrador y al registrar una nota sin contenido. `avanzar` manda
a la tablet la pregunta, el aviso informativo (sin valores, se confirma solo) o el borrador `B<n>`.

## Decisions

- **El parte se guarda como `Borrador` en `avanzar`, después de mandar el borrador `B<n>`:** es el momento en que el
  operador lo ve. Una pregunta de equipo no es un borrador: todavía no hay parte que mostrar.
- **El mismo registro pasa a `Confirmado`** por el upsert existente, con las filas finales. No hay historial de
  versiones del borrador en `partes`: cada versión ya queda en `mensajes_tablet`.
- **Las notas sin valores y sin contenido van directo a `Confirmado`**, como hoy: el operador no tiene nada que
  confirmar y el corrector espera su evento.
- **Una nota abandonada deja el parte en `Borrador`**: nunca se confirmó y no generó eventos.
- **Sin tests nuevos:** es un `INSERT` en un punto del flujo. Se verifica en la base después de una corrida.

## Risks / Trade-offs

- Un borrador que se retoma después de un reinicio vuelve a guardarse como `Borrador`: el upsert lo deja igual.
