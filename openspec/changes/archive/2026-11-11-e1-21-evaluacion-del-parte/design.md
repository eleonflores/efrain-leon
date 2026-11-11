## Context

`evaluar_partes.py` lee `/api/verdad`, `/api/registro` y `/api/estado` de la planta en desarrollo y compara, por nota,
el primer borrador con lo que dijo el operador, si preguntó en las ambiguas y de más en las claras, y las demoras.
El corrector guarda por escenario un JSON con `verdad` (notas y diálogos con el operador virtual) y `registro` (lo
que publicó el sistema, con `ts_real` y si validó), con el mismo formato que la API.

## Decisions

- **`--corrida` en lugar de una copia del cálculo:** el script lee la verdad y el registro del JSON y sigue igual.
  Sin `--corrida`, lee la API como antes.
- **Resultados de la corrida del change `e1-20`:** es el código que se entrega. Se versionan los dos JSON de salida
  (resumen y detalle por nota) y un README con la tabla y cómo leerla.
- **Emparejar por equipo y variable primero:** cada lectura de la verdad se busca en el primer borrador por equipo y
  variable, y solo si no está, por valor parecido (para detectar un equipo equivocado). Emparejar solo por valor daba
  16/18 aciertos de equipo en `martes-tranquilo` con todos los borradores confirmados: 1600 psi son 112,5 kg/cm², y
  la descarga de B-102 se cruzaba con la de B-101 (112 kg/cm²).
- **Costo:** USD 0 fijo (todo es local); los tokens salen de `/api/estado` cuando se evalúa contra la planta en
  desarrollo. La corrida del corrector no guarda el estado del visor.
- **Spec nuevo `evaluacion`:** ninguna capacidad cubría la medición, y ponerla en `extraccion-del-parte` mezclaría lo
  que el sistema hace con cómo se mide. Por ahora tiene solo el requisito del parte; las otras suites (STT, LLM,
  reglas, RAG) pueden sumarse después.
- **Sin tests nuevos:** el script es la medición; su salida es el resultado que se revisa.

## Risks / Trade-offs

- La verdad de la corrida refleja una sola ejecución: Whisper puede transcribir distinto un número entre corridas
  (README del repo), así que los aciertos varían un poco de una corrida a otra.
