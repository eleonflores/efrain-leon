# Tareas

## 1. Registro

- [x] 1.1 Paso `seguridad` en cada nota; con alerta, después de `alertar`.
- [x] 1.2 Paso `deteccion` en `publicar_evento`, con la herramienta según el origen, las filas y los motivos.
- [x] 1.3 `consultar_historian`: mide y registra cada consulta; `rango_historico`, `marcar_fuera_de_rango` y
      `tendencia` reciben la nota.
- [x] 1.4 La transcripción registra `audio_url` y `descarga_ms`.

## 2. Reporte

- [x] 2.1 `python -m sistema.metricas`: sección "Modelos, reglas y consultas"; duraciones de menos de 1 s en ms.

## 3. Verificación y cierre

- [x] 3.1 Suite verde y `openspec validate --strict`.
- [x] 3.2 En vivo: recorrida, nota con "la bomba" y alerta S1; los pasos nuevos están y el de seguridad queda después
      del mensaje `-SEG`.
- [x] 3.3 Corrector local sobre `martes-tranquilo` y `fuga-sin-enlace`: 91,3, aprueba; B2, E1–E3 y F1 al 100 %, sin
      eliminatorias.
- [x] 3.4 Archivar el change (`openspec archive`).
