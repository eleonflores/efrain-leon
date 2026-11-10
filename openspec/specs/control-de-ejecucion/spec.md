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
si salió bien y el detalle del error.

#### Scenario: Nota resuelta por reglas
- **WHEN** las reglas resuelven una nota
- **THEN** quedan registrados la transcripción y la extracción por reglas, con 0 tokens

### Requirement: Consumo de tokens publicado

El sistema SHALL publicar en `sistema/metricas` el consumo acumulado por modelo cuando hubo tokens, con totales iguales
a la suma del desglose, un modelo por fila y fecha con zona horaria.

#### Scenario: Corrida sin LLM
- **WHEN** ninguna nota necesitó el LLM
- **THEN** no se publica `sistema/metricas`

### Requirement: Todo lo publicado respeta el contrato

Todo mensaje a `sistema/*` SHALL construirse con los modelos de `planta_contrato` (validados antes de publicar), y todo
mensaje recibido de `planta/*` SHALL validarse al entrar; uno inválido SHALL descartarse sin cortar la recepción.

**Razón:** el corrector cuenta los mensajes inválidos (criterio F1).

#### Scenario: Lectura de sensor malformada
- **WHEN** llega a `planta/sensores/…` un mensaje que no valida contra `LecturaSensor`
- **THEN** se descarta y la recepción sigue
