## Why

El anexo de la Entrega 1 pide que el sistema escuche `planta/recorridas` y "baje el audio y las fotos de
`http://sim:8100{audio_url}`". Hoy baja solo el audio: las fotos quedan como direcciones (`/media/fotos/...`) en las
filas del parte, en el contexto del `Escalado` y en la alerta que se encola hacia la nube. La nube está fuera de
`planta-lan` y no puede abrir `http://sim:8100`, así que recibe una dirección que no sirve: el `Escalado` llega sin
la evidencia que el enunciado pide (parte, fotos y tendencia).

El corrector no lo mide (D y el análisis con fotos entran en la Entrega 2), pero es un requisito explícito del anexo.

## What Changes

- Al llegar una nota, una tarea aparte baja sus fotos de la planta, con reintentos, y las guarda en la base. No
  demora la transcripción ni la alerta. Cada descarga queda registrada como consulta a la planta.
- El `Escalado` y la `AlertaSeguridad` se encolan hacia la nube con el contenido de cada foto (tipo y base64). Una
  foto que no se pudo bajar va con su dirección y el motivo.
- La política de memoria suma la tabla de fotos.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `deteccion-en-planta`: las fotos se bajan al llegar la nota y viajan con el contexto del `Escalado`.
- `alerta-de-seguridad`: la alerta se encola con el contenido de las fotos.

## Impact

- `src/sistema/agente.py`, `src/sistema/persistencia/db.py` (tabla `fotos`), `docs/memoria.md`.
- Servicio `sistema`: una descarga de ~25 KB por foto por la red de planta, en segundo plano. El payload de la cola
  crece ~33 KB por foto. Sin impacto medible en CPU ni memoria.
- Entrega 1. Toca el flujo de la nota y el de la alerta: se verifica B2, F1 y la cola sin enlace (E1–E3).
