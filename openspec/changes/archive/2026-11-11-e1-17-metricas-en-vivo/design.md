## Context

Cada paso de una nota ya queda en la tabla `pasos` (etapa, modelo o herramienta, tokens, duración, ok, detalle). La
planta acepta en `sistema/metricas` un `ConsumoTokens` (en `planta_sim/metricas.py`, fuera de `planta_contrato`):
totales iguales a la suma del desglose, un modelo por fila, fecha con zona, `extra="forbid"`, sin NaN. El visor lo
muestra en el plano con tokens de entrada, salida y tokens por segundo de generación por modelo, y lo marca "Sin
actualizar" si el `ts` tiene más de 30 s reales. La planta guarda el último snapshot: no suma entre mensajes.

## Decisions

- **Tokens de Whisper:** la suma de `len(segmento.tokens)`; entrada 0 (es audio). La velocidad usa el tiempo de
  transcribir, que es lo que tarda en dar texto (encoder incluido).
- **Tiempo de generación del LLM:** `response_metadata["eval_duration"]` de Ollama, en `detalle.generacion_ms`. Un
  timeout no trae metadatos: suma una llamada sin tokens.
- **Sin cambio de esquema:** los tiempos van en `detalle` (jsonb). La base local del usuario sobrevive a los
  reinicios; el corrector la borra entre escenarios.
- **Velocidad:** tokens de salida / tiempo de generación, sumado sobre las llamadas con salida. Las filas viejas sin
  `generacion_ms` usan la duración completa y marcan `velocidad_estimada` (es la convención del visor).
- **Modelos cargados con 0 tokens:** se publican desde el arranque, para que el panel muestre qué modelos usa el
  sistema aunque el LLM no haya hecho falta.
- **Cada 10 s, en tiempo real:** tarea propia, independiente del latido. El `ts` de `sistema/metricas` es el reloj
  real porque el visor lo compara con el reloj del navegador.
- **El armado es una función pura** (`metricas.consumo_tokens`): el test la valida contra una copia del modelo del
  visor. Un `sistema/metricas` inválido le resta a F1.
- **El reporte lee solo la base.** Anda con el enlace caído y sin la planta. Los percentiles los calcula Postgres
  (`percentile_cont`).
- **Demora medida en el proceso:** `EstadoNota.t0` (`perf_counter`) al llegar la nota y un paso `primer_mensaje` al
  publicar el primer mensaje a la tablet. Es tiempo real, como mide el corrector. No sale de `notas.creada`: la planta
  reinicia los ids al arrancar y esa fecha queda de la primera vez que llegó el id. Una nota retomada después de un
  reinicio no registra demora si ya había hablado con la tablet.
- **Primer borrador confirmado:** nota `confirmada` con un solo mensaje `-B<n>`. Es la misma idea que A2, medida con lo
  que guarda el sistema.

## Risks / Trade-offs

- La velocidad de Whisper incluye el encoder: es menor que la del decoder solo. Se acepta porque es la que importa
  para la alerta (cuánto tarda en haber texto).
- El reporte cuenta todo lo que hay en la base. En la base local mezcla sesiones; en el corrector, cada escenario
  arranca vacío.
