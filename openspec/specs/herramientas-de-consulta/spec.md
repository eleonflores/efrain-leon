# herramientas-de-consulta Specification

## Purpose

Darle a un modelo (por LangChain o por MCP) consultas de solo lectura sobre la planta con contratos estrictos: qué
equipos hay, qué midieron sus sensores, qué órdenes tuvieron, qué repuestos y tareas existen y qué dicen los manuales.
Una consulta que falla devuelve un error que el modelo puede leer y corregir.

## Requirements

### Requirement: Seis tools de solo lectura

El sistema SHALL exponer estas tools, todas de solo lectura e idempotentes:

| Tool | Fuente | Devuelve |
|---|---|---|
| `consultar_equipos` | `GET /api/planta` | Equipos, nombres informales, unidad del manómetro, sensores con límites de alarma |
| `consultar_historial_sensor` | Historiador de la planta (45 días) | Resumen contra los límites y una serie submuestreada (2 a 200 puntos) |
| `consultar_historial_ordenes` | `GET /api/historial-ordenes` | Las órdenes más nuevas del equipo o la tarea (1 a 50) |
| `consultar_repuestos` | Materiales | Repuestos con costo, stock por almacén y en qué tareas se usan |
| `consultar_tareas` | Materiales | Tareas estándar y no estándar con horas, si detienen el equipo, repuestos y costo |
| `buscar_en_manuales` | Índice RAG (ver `busqueda-en-manuales`) | Fragmentos con su cita |

Ninguna tool SHALL modificar nada en la planta, los materiales ni la base.

#### Scenario: Equipo por su nombre informal
- **WHEN** se llama `consultar_equipos` con `tag: "la de la punta"`
- **THEN** devuelve B-101 con sus sensores y límites

### Requirement: Contratos estrictos

Cada tool SHALL tener un modelo Pydantic de entrada y otro de salida con `extra="forbid"`, valores cerrados como
`Literal`, rangos en los números y descripciones con un ejemplo en cada campo. El esquema de entrada que ve el modelo
SHALL ser exactamente ese contrato.

#### Scenario: Argumento de más
- **WHEN** se llama una tool con un campo que no está en su contrato
- **THEN** devuelve `ARGUMENTOS_INVALIDOS` con el campo sobrante en el mensaje

#### Scenario: Argumentos que se excluyen
- **WHEN** se llama `consultar_repuestos` con `equipo` y `codigo` a la vez
- **THEN** devuelve `ARGUMENTOS_INVALIDOS` diciendo que se pasa uno u otro

### Requirement: Las tools no lanzan excepciones

Toda falla SHALL volver como `ErrorHerramienta` con `codigo` estable, `mensaje` que dice cómo corregir y
`reintentable`. Los errores de la planta que no son transitorios (equipo inexistente, argumentos inválidos) SHALL ser
`reintentable: false`; un timeout o la planta caída, `true`.

Cada tool SHALL tener un timeout total de 20 s. Las consultas a la planta SHALL reintentarse solo ante fallas
transitorias (timeout, conexión caída, 5xx), hasta 2 veces con backoff exponencial; un 4xx o un JSON roto SHALL NOT
reintentarse.

**Razón:** el loop del agente tiene que seguir: un error estructurado le dice al modelo si corrige los argumentos o
sigue sin el dato. Reintentar un 4xx no lo arregla.

Las consultas a la planta SHALL ir directo por la LAN, sin el proxy del enlace, y las fechas al historiador SHALL
mandarse en hora de planta con offset `-03:00` explícito y segundos.

**Razón:** el historiador compara las fechas como texto contra `-03:00`; otra zona u otro formato filtran mal. El
offset es fijo porque Argentina no tiene horario de verano desde 2009, y así no se depende de `tzdata`.

#### Scenario: Equipo inexistente
- **WHEN** se llama `consultar_historial_sensor` con `tag: "B-999"`
- **THEN** devuelve `EQUIPO_INEXISTENTE` con `reintentable: false` y la lista de equipos válidos en el mensaje

#### Scenario: Planta caída
- **WHEN** la API de la planta no responde
- **THEN** la tool devuelve un error con `reintentable: true` antes de 20 s

### Requirement: Servidor MCP

El sistema SHALL publicar las tools por un servidor MCP (Streamable HTTP sin estado, `:8001/mcp`, servicio
`herramientas`), cada una con su `inputSchema` y `outputSchema` tomados del contrato y las annotations
`readOnlyHint: true`, `idempotentHint: true` y `destructiveHint: false`. Una tool inexistente SHALL ser un error
JSON-RPC; una consulta que falla SHALL ser un resultado con `isError: true` y el `ErrorHerramienta` en
`structuredContent`. El puerto SHALL NOT publicarse fuera de la red de Docker.

**Razón:** el servidor no tiene autenticación. Separar los dos errores deja que el modelo lea y corrija los suyos.

#### Scenario: Listado de tools
- **WHEN** un cliente MCP lista las tools
- **THEN** recibe las seis con su esquema de entrada con `additionalProperties: false`

#### Scenario: Consulta fallida por MCP
- **WHEN** un cliente MCP llama `consultar_equipos` con un TAG que no existe
- **THEN** recibe un resultado con `isError: true` y el error estructurado, no un error de protocolo
