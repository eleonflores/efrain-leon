# Tareas

## 1. Evaluación

- [x] 1.1 `evaluar_partes.py --corrida`: lee la verdad y el registro del JSON del corrector; el resumen suma escenario
      y costo.
- [x] 1.2 Correr sobre `martes-tranquilo` y `fuga-sin-enlace` de la corrida del change `e1-20` y guardar la salida en
      `evaluacion/partes/`.
- [x] 1.3 `evaluacion/partes/README.md` con la tabla de resultados y cómo leerla; la tabla de suites del `README.md`
      apunta ahí.

## 2. Verificación y cierre

- [x] 2.1 Los números coinciden con el informe del corrector de esa corrida (A2, A4a, A4b y la demora de la alerta).
- [x] 2.2 `openspec validate --strict`.
- [x] 2.3 Archivar el change (`openspec archive`).
