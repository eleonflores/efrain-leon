# control-de-ejecucion Specification

## Purpose

Que ninguna nota consuma recursos sin límite ni tumbe el sistema, que cada paso quede registrado (qué modelo o
herramienta, con qué argumentos, cuántos tokens, cuánto costó y cuánto tardó) y que nada inválido llegue a la planta.
## Requirements
### Requirement: Cada nota tiene límites

Cada nota SHALL correr en su propia tarea, con:

- un timeout global de `TIMEOUT_NOTA_S` (180 s) para llegar a la tablet;
- un presupuesto de `MAX_PASOS_LLM_POR_NOTA` (4) llamadas al LLM y `MAX_TOKENS_POR_NOTA` (12000) tokens;
- un tope de `MAX_INTENTOS_BORRADOR` (3) borradores.

Al agotarse cualquiera, la nota SHALL quedar `abandonada` con el motivo en la tabla `pasos`. Un error en una nota
SHALL NOT afectar a las demás ni al sistema.

#### Scenario: Presupuesto agotado
- **WHEN** una nota ya usó sus 4 llamadas al LLM
- **THEN** la siguiente llamada no se hace y la nota queda abandonada con "presupuesto agotado"

#### Scenario: Nota rota
- **WHEN** el audio de una nota no se puede bajar
- **THEN** esa nota queda abandonada con el error y las demás siguen

### Requirement: El LLM atiende de a una llamada

El sistema SHALL hacer una llamada al LLM por vez, con temperatura 0, salida estructurada validada y
`LLM_TIMEOUT_S` (45 s). El LLM SHALL quedar cargado en memoria (`keep_alive` de 24 h).

#### Scenario: Dos notas necesitan el LLM
- **WHEN** dos notas llaman al LLM a la vez
- **THEN** la segunda espera a que termine la primera

### Requirement: Cada paso queda registrado

El sistema SHALL registrar en la tabla `pasos` cada transcripción, extracción por reglas, llamada al LLM y abandono,
con nota, etapa, modelo o herramienta, argumentos, tokens de entrada y salida, costo (cero: todo es local), duración,
si salió bien y el detalle del error. La transcripción SHALL registrar los tokens de texto que generó, los segundos de
audio y el tiempo de transcribir; la llamada al LLM, el tiempo de generación que informa Ollama (`generacion_ms`). El
primer mensaje de cada nota a la tablet SHALL registrarse como paso `primer_mensaje`, con la demora desde que la nota
llegó al proceso.

**Razón:** la planta reinicia los ids de nota cuando arranca de nuevo, y `notas.creada` queda de la primera vez que
llegó ese id: medir la demora contra esa fecha dio 14.351 s de alerta en la base de la demo.

#### Scenario: Nota resuelta por reglas
- **WHEN** las reglas resuelven una nota
- **THEN** quedan registradas la transcripción, con sus tokens de texto, y la extracción por reglas, con 0 tokens

#### Scenario: LLM por timeout
- **WHEN** la llamada al LLM corta por timeout
- **THEN** queda registrada sin tokens, con `ok` falso y el `TimeoutError` en el detalle

#### Scenario: Alerta de seguridad
- **WHEN** una nota insegura da la alerta 6 s después de llegar
- **THEN** queda un paso `primer_mensaje` de 6 s con el id del mensaje `TAB-<nota>-SEG`

### Requirement: Consumo de tokens publicado

El sistema SHALL publicar en `sistema/metricas`, cada 10 s reales desde que la base está lista, el consumo acumulado
de cada modelo que corre en el servicio `sistema` (el de transcripción y el LLM), aunque todavía tenga 0 tokens. La
velocidad SHALL ser tokens de salida sobre segundos de generación de las llamadas con salida: una llamada sin tokens
(un timeout) suma al total y no baja la velocidad. Las llamadas registradas sin tiempo de generación SHALL usar la
duración completa y marcar `velocidad_estimada`. Los totales SHALL ser iguales a la suma del desglose, con un modelo
por fila y fecha con zona horaria.

**Razón:** con reglas primero el LLM atiende ~5 % de las notas, así que publicar solo cuando el LLM gastó tokens
dejaba el panel del visor vacío casi siempre. El visor da la métrica por vencida a los 30 s reales: cada 60 s, junto
con el latido, se veía "Sin actualizar" la mitad del tiempo. `sistema/metricas` no frena el reloj por eventos de la
planta, pero un mensaje que no valida cuenta como inválido en F1.

#### Scenario: Arranque
- **WHEN** el sistema arrancó y todavía no procesó notas
- **THEN** el visor muestra el modelo de transcripción y el LLM, los dos con 0 tokens

#### Scenario: Nota resuelta por reglas
- **WHEN** una nota se transcribe y la resuelven las reglas
- **THEN** la fila del modelo de transcripción suma los tokens de texto y la del LLM no cambia

#### Scenario: LLM por timeout
- **WHEN** una llamada al LLM generó 50 tokens en 12,5 s y otra cortó por timeout
- **THEN** la fila del LLM muestra 4 tok/s

### Requirement: Todo lo publicado respeta el contrato

Todo mensaje a `sistema/*` SHALL construirse con los modelos de `planta_contrato` (validados antes de publicar), y todo
mensaje recibido de `planta/*` SHALL validarse al entrar; uno inválido SHALL descartarse sin cortar la recepción.

**Razón:** el corrector cuenta los mensajes inválidos (criterio F1).

#### Scenario: Lectura de sensor malformada
- **WHEN** llega a `planta/sensores/…` un mensaje que no valida contra `LecturaSensor`
- **THEN** se descarta y la recepción sigue

### Requirement: Reporte de funcionamiento

El sistema SHALL ofrecer `python -m sistema.metricas`, de solo lectura sobre la base, que muestra en tiempo real:

- las notas por fase y el costo (USD 0, todo local);
- la demora de cada nota hasta su primer mensaje en la tablet y hasta la alerta de seguridad (p50, p95 y máximo);
- por modelo o herramienta: llamadas, fallas, timeouts, duración p50 y p95, tokens y velocidad; para la
  transcripción, también los segundos de audio y el tiempo de transcribir sobre el audio; para las reglas, las notas
  que resolvieron completas;
- las notas confirmadas al primer borrador, las preguntas y las correcciones;
- los abandonos por motivo y la cola hacia la nube (enviados y pendientes).

**Razón:** la latencia es lo que manda en CPU (la alerta tiene 30 s y el corrector mide en tiempo real). Todo esto ya
está en `pasos`, `notas` y `mensajes_tablet`, pero leerlo a mano no deja ver la fluidez: una consulta sobre la demo
del 10/11 mostró que las dos llamadas al LLM de la sesión cortaron por timeout, algo que los logs no dejan ver.

#### Scenario: Después de una corrida
- **WHEN** se corre `docker compose exec sistema python -m sistema.metricas`
- **THEN** muestra la demora nota → tablet en p50 y p95 y, por modelo, la velocidad y los timeouts

#### Scenario: Enlace caído
- **WHEN** el enlace está caído y hay eventos sin sincronizar
- **THEN** el reporte sale igual y muestra los pendientes de la cola

