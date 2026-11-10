# Evaluación del LLM en la extracción del parte

Mide los LLM locales candidatos armando el borrador con el pipeline real (`numeros` → LLM con salida estructurada →
`parte.armar_borrador`) y comparándolo con la verdad de campo con **la misma función del operador virtual**
(`planta_sim.dialogo._comparar`): sin problemas, el operador habría confirmado al primer intento (criterio A2).

```bash
python evaluacion/llm/bench_llm.py --capturas .local/capturas --modelos qwen3.5:2b \
    --planta-sim ../academia2026-tp/planta/sim --salida evaluacion/llm/resultados
```

Las notas salen de `evaluacion/capturar_escenario.py` (`martes-tranquilo` y `fuga-sin-enlace`, sin las de seguridad).

## Resultados (Ollama 0.40.16 en CPU, 2 hilos, PC de trabajo)

| Modelo | Notas | Parte correcto | JSON válido | Latencia p50 / p95 | Tokens entrada / salida |
| --- | ---: | ---: | ---: | ---: | ---: |
| qwen3.5:2b | 12 | 33 % | 50 % | 79 s / 90 s (timeout) | 430 / 53 |
| ministral-3:3b | — | — | — | no completada | — |
| gemma4:e2b | — | — | — | descartado: 4,6 GB no entra en el contenedor de 4 GB | — |

Velocidad medida en el log de Ollama: 13–26 tokens/s de entrada y 3,5–4,3 tokens/s de salida. La medición corrió con
otra medición en paralelo, así que es pesimista; aun sin competencia, una nota no baja de decenas de segundos.

**Conclusión:** el LLM en CPU no sirve como camino principal del parte (la planta no espera 40–80 s por nota). La
extracción va primero por reglas ([../reglas/](../reglas/)) y el LLM queda de respaldo con timeout.
