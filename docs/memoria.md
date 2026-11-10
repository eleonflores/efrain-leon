# Política de memoria

> Qué recuerda el sistema, dónde, por cuánto tiempo y quién lo puede leer (módulo 1.1: la memoria tiene reglas de
> escritura, lectura, caducidad y privacidad). Todo vive en PostgreSQL 16, en la PC de planta (`db`), para que funcione
> sin enlace y sobreviva a un corte de luz.

## Memoria de corto plazo: la conversación de cada nota

| Qué | Tabla | Se escribe | Se lee | Vence |
| --- | --- | --- | --- | --- |
| La nota (id, ts, audio, fotos), su transcripción, la fase del diálogo, el borrador actual y el número de intento | `notas` | En cada transición (recibida → transcrita → pregunta/borrador → confirmada) | Al llegar una respuesta del operador y al reiniciar (se retoman las notas abiertas) | 30 días después de cerrada |
| Cada mensaje a la tablet y la respuesta del operador | `mensajes_tablet` | Al enviar y al recibir | Para saber a qué nota corresponde una respuesta | 30 días |

El contexto que ve el LLM es **solo la nota actual** (y, en una corrección, el borrador actual): no se arrastra el
historial de otras notas. Así una nota mal transcripta o con instrucciones incrustadas no contamina las siguientes.

## Memoria de largo plazo: lo que la planta necesita recordar

| Qué | Tabla | Por qué | Vence |
| --- | --- | --- | --- |
| Partes confirmados | `partes` | Es el registro de la recorrida (reemplaza la planilla de papel) y el historial propio para rangos de variables sin sensor | 2 años (como el historial de órdenes) |
| Eventos (`SinNovedad`, `Escalado`, `AlertaSeguridad`) con su contexto | `eventos` | Evidencia de cada decisión; idempotencia (el mismo id no se publica dos veces) | 2 años |
| Registro de pasos: modelo, herramienta, argumentos, tokens, costo y tiempo | `pasos` | Trazabilidad que pide el enunciado (F) y medición de consumo para el INFORME | 90 días |
| Cola hacia la nube | `salida_nube` | Lo que tiene que salir de la planta espera acá, en orden, hasta que vuelve el enlace | Se marca enviado; se borra a los 7 días de enviado |
| Fragmentos del corpus con embeddings | `rag_fragmentos` (RAG, ver `docs/rag.md`) | Conocimiento de los manuales; se regenera desde los documentos | No vence; se reindexa si cambia el corpus |

## Lo que no se guarda

- Los **audios** de las notas: quedan en la planta (`/media/audios`); se guarda la URL, no el archivo.
- El razonamiento interno del modelo: se registran las entradas, las salidas validadas y las métricas, no "lo que
  pensó".
- Credenciales o secretos: no van en prompts ni en la base.

## Privacidad

Las notas tienen el nombre del operador. Solo el sistema de planta escribe; las herramientas de consulta usan solo
lectura. Lo que se sincroniza a la nube son los eventos escalados y las alertas con su contexto técnico, no las
transcripciones completas del resto de las notas.

## Caducidad

La limpieza es un `DELETE` por fecha que corre una vez por día de planta. En la Entrega 1 la política está escrita y
las tablas tienen las fechas para aplicarla; el job de limpieza entra con la Entrega 2.
