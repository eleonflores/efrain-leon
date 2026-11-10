# Evaluación de las reglas del parte y de la detección

Genera notas con **el mismo código del operador virtual de la planta** (`planta_sim.operador.OperadorVirtual` sobre
`planta_sim.modelo.Planta`), con fallas al azar (F01–F09), bombas paradas, en mantenimiento o disparadas y las
ambigüedades a propósito ("la bomba" a secas, diferenciales dichos "dieciocho"), y mide con los criterios de la
corrección:

- **A2:** el primer borrador se confirmaría (`planta_sim.dialogo._comparar`);
- **A4:** detecta las ambigüedades y no pregunta en notas claras;
- **B1:** la decisión SinNovedad/Escalado por equipo coincide con la del corrector (`correccion/puntuar.py`).

```bash
python evaluacion/reglas/evaluar_reglas.py --repo-planta ../academia2026-tp --notas 400
```

## Resultados (400 notas, semilla 7)

| Métrica | Resultado |
| --- | ---: |
| Notas resueltas por las reglas (sin LLM) | 400 / 400 |
| Primer borrador confirmable | 382 / 400 (95,5 %) |
| Ambigüedades detectadas | 32 / 32 |
| Preguntas de más | 0 |
| Decisión B1 igual a la del corrector | 672 / 675 |

Las 18 notas con primer borrador no confirmable son casi todas de goteo de empaquetadura: la verdad de campo guarda el
goteo con un valor en gotas/min que el operador no dicta. El operador lo informa en su respuesta y el segundo
borrador se confirma. Las 3 diferencias de B1 son de notas ambiguas evaluadas sin el paso de la pregunta (en el
sistema, la unidad del manómetro se completa después de que el operador elige la bomba).
