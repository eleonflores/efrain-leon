# Tareas

## 1. El aviso sigue a la corrección

- [x] 1.1 `dialogo.aplicar`: una corrección de valor, unidad o equipo borra `fuera_de_rango` de la fila que toca.
- [x] 1.2 `Sistema.procesar_respuesta`: después de `aplicar`, `marcar_fuera_de_rango` sobre las filas.
- [x] 1.3 Test: la corrección de 150 a 115 de la demo deja la fila sin aviso.

## 2. Verificación y cierre

- [x] 2.1 Suite verde y `openspec validate --strict`.
- [x] 2.2 En vivo: la misma corrección en la planta muestra el borrador sin el aviso viejo.
- [x] 2.3 Archivar el change (`openspec archive`).
