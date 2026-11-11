## Why

El enunciado (F, Registro) pide que cada decisión quede registrada con el modelo usado, las herramientas llamadas y
sus argumentos, los tokens, el costo y el tiempo de cada paso. Hoy la tabla `pasos` registra lo que usa un modelo
(transcripción, LLM), la extracción por reglas, el abandono y la demora a la tablet. Las decisiones del código quedan
solo por su resultado: la alerta en `notas.seguridad`, el SinNovedad/Escalado en el `resumen` del evento. Las
consultas al historiador (rango de 45 días y tendencia de 6 h) no quedan en ningún lado.

El corrector no lo mide: "el registro de tokens y costo" es de revisión manual (`correccion/README.md`).

## What Changes

- La detección de seguridad queda registrada en cada nota, con las condiciones encontradas o ninguna. Con alerta, se
  registra después de publicarla.
- Cada decisión SinNovedad/Escalado (por parte, por sensor o por nota sin contenido) queda registrada con el equipo,
  la entrada y los motivos.
- Cada consulta a la API de la planta hecha para una nota o un evento queda registrada (hoy, el historiador: equipo,
  sensor, rango, muestras, duración y si salió bien).
- La transcripción registra el audio que bajó y cuánto tardó la descarga.
- El reporte `python -m sistema.metricas` muestra las consultas y decisiones nuevas, con las duraciones cortas en ms.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `control-de-ejecucion`: el registro por paso suma la detección de seguridad, la decisión de detección y las
  consultas al historiador.

## Impact

- `src/sistema/agente.py` y `src/sistema/metricas.py`. Sin cambios de esquema (todo va en `pasos`).
- Servicio `sistema`: un `INSERT` por decisión o consulta, en milisegundos. La alerta no espera al registro.
- Entrega 1, sin cambio de criterios del corrector. Toca el camino de la alerta: se verifica B2 y su demora.
