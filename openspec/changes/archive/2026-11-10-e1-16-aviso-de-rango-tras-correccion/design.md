## Context

El aviso de rango vive en `FilaBorrador.fuera_de_rango` y lo pone `Sistema.marcar_fuera_de_rango` al armar el
primer borrador. `dialogo.aplicar` cambia valor, unidad o equipo de una fila sin tocar ese campo.

## Decisions

- **`aplicar` borra el aviso de la fila que corrige** (valor, unidad o equipo). Es una función pura: el
  comportamiento queda testeado sin la planta.
- **El agente recalcula después de aplicar**, con `marcar_fuera_de_rango` sobre todas las filas. Las que no se
  tocaron vuelven a dar el mismo aviso; las corregidas, el que corresponde al valor nuevo. El rango sale de la caché
  (6 h de planta), así que no hay consultas extra al historiador.
- Una fila agregada con "te faltó…" ya nace sin aviso y entra en el mismo recálculo.

## Risks / Trade-offs

- Ninguno sobre el corrector: el operador virtual no lee el texto del borrador.
