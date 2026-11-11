# Tareas

## 1. Bajar las fotos

- [x] 1.1 Tabla `fotos` (`url`, `tipo`, `contenido`, `bajada`) y métodos para guardar y leer.
- [x] 1.2 `Sistema.bajar_fotos`: tarea por nota al llegar, tres intentos, paso `consulta` con herramienta `fotos`.

## 2. Las fotos viajan a la nube

- [x] 2.1 `Sistema.fotos_para_la_nube`: `{url, tipo, contenido_b64}` o `{url, error}`; reintenta una vez si falta.
- [x] 2.2 El payload del `Escalado` y el de la alerta llevan el contenido; el contexto guardado en `eventos`, las
      direcciones.

## 3. Documentación

- [x] 3.1 `docs/memoria.md`: la tabla `fotos` y cuánto se guarda.

## 4. Verificación y cierre

- [x] 4.1 Suite verde y `openspec validate --strict`.
- [x] 4.2 En vivo con el enlace caído: alerta S1 con foto; la foto está en `fotos`, la alerta sale en menos de 30 s y,
      al volver el enlace, la nube recibe el contenido.
- [x] 4.3 Corrector local sobre `martes-tranquilo` y `fuga-sin-enlace`: 91,3, aprueba; B2, E1–E3 y F1 al 100 %, sin
      eliminatorias.
- [x] 4.4 Archivar el change (`openspec archive`).
