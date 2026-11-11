# Tareas

## 1. Registro

- [x] 1.1 `stt`: `transcribir` devuelve texto y tokens generados; el agente los registra con `generacion_ms`.
- [x] 1.2 `ModeloLocal.estructurado`: `generacion_ms` desde `eval_duration` de Ollama en el detalle del paso.

## 2. Consumo en el visor

- [x] 2.1 `metricas.consumo_tokens`: arma `ConsumoTokens` desde las filas de la base y los modelos cargados.
- [x] 2.2 `Base.consumo_por_modelo` con tiempo de generación y tiempo estimado por separado.
- [x] 2.3 Tarea `metricas` del agente: publica cada 10 s; sale del latido.
- [x] 2.4 Test: el armado valida contra el modelo del visor (arranque, timeout, filas sin tiempo de generación,
      modelo que ya no está cargado) y la velocidad es salida sobre tiempo de generación, ponderada entre modelos.

## 3. Reporte

- [x] 3.1 Paso `primer_mensaje` con la demora medida en el proceso.
- [x] 3.2 `Base.estadisticas` (consultas agregadas) y `python -m sistema.metricas` (formato).

## 4. Documentación

- [x] 4.1 README: cómo ver modelos y fluidez en vivo, con una salida real.
- [x] 4.2 INFORME: tokens de la transcripción y velocidad de generación.

## 5. Verificación y cierre

- [x] 5.1 Suite verde y `openspec validate --strict`.
- [x] 5.2 En vivo: el visor muestra Whisper y el LLM "Acumulado histórico"; el reporte sale después de una recorrida.
- [x] 5.3 Corrector local sobre `martes-tranquilo` y `fuga-sin-enlace`: 90,4, aprueba, F1 al 100 %. El punto de
      diferencia con 91,3 es una transcripción ("600" por "mil seiscientos") que varía entre corridas.
- [x] 5.4 Archivar el change (`openspec archive`).
