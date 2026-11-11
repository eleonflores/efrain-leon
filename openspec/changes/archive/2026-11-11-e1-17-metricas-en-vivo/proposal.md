## Why

Para defender el sistema hay que poder mostrar qué modelos usa y qué tan fluido anda. Hoy eso no se ve:

- El panel de consumo del visor de la planta (`sistema/metricas`) queda casi siempre vacío. Se publica solo cuando
  hubo tokens del LLM, y con reglas primero el LLM atiende ~5 % de las notas. Cuando se publica, sale cada 60 s y el
  visor lo da por vencido a los 30 s ("Sin actualizar").
- La transcripción, que corre en cada nota, no registra tokens: no aparece en el panel.
- La velocidad del LLM se calcula con la duración completa de la llamada (entrada + generación), no con el tiempo de
  generación que pide el visor.
- La demora de cada nota hasta la tablet, la de la alerta y cuántas notas se confirman al primer borrador están en la
  base, pero solo se ven con consultas a mano. Una consulta así sobre la demo del 10/11 mostró que las dos llamadas al
  LLM de esa sesión cortaron por timeout, algo que los logs no dejan ver.

El corrector no puntúa estas métricas: "el registro de tokens y costo" es de revisión manual
(`correccion/README.md`). `sistema/metricas` no frena el reloj de la planta ni entra en el registro que puntúa, pero
un mensaje que no valida contra el modelo del visor sí cuenta como inválido (F1).

## What Changes

- La transcripción registra los tokens de texto que genera Whisper y su tiempo; el LLM registra el tiempo de
  generación que informa Ollama (`eval_duration`).
- `sistema/metricas` se publica cada 10 s, desde el arranque, con una fila por modelo cargado en el servicio
  `sistema` (Whisper y el LLM), aunque todavía tengan 0 tokens. La velocidad se calcula sobre el tiempo de
  generación; los timeouts suman al total y no bajan la velocidad.
- Nuevo comando `python -m sistema.metricas`: reporte de fluidez leído de la base (demora nota → tablet y nota →
  alerta en p50/p95, por modelo llamadas, fallas, timeouts, duración, tokens y velocidad, tiempo de transcripción
  sobre el audio, notas resueltas por reglas, confirmadas al primer borrador, preguntas, correcciones y cola hacia la
  nube).
- README e informe: cómo ver los modelos y la fluidez en vivo.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `control-de-ejecucion`: el registro por paso suma tokens de la transcripción y tiempo de generación del LLM; el
  consumo se publica siempre y con velocidad de generación; nuevo reporte de funcionamiento.

## Impact

- `src/sistema/procesamiento/stt.py`, `src/sistema/llm/modelo.py`, `src/sistema/agente.py`,
  `src/sistema/persistencia/db.py`, nuevo `src/sistema/metricas.py`; `README.md`, `INFORME.md`.
- Servicio `sistema`. Una consulta agregada sobre `pasos` cada 10 s y un mensaje MQTT chico: sin impacto medible en
  las 2 CPU del servicio. Sin cambios de esquema (los tiempos nuevos van en `pasos.detalle`).
- Entrega 1, sin cambio de criterios del corrector; F1 protegido por un test de las reglas de validación del visor.
