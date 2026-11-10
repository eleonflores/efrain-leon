# latido-y-sincronizacion Specification

## Purpose

Que la planta sepa en todo momento que el sistema está vivo, si tiene enlace y cuánto tiene pendiente de mandar a la
nube, y que lo que va a la nube no se pierda cuando el enlace se cae.

## Requirements

### Requirement: Latido inmediato y periódico

El sistema SHALL publicar `EstadoSistema` en `sistema/estado` (con `enlace_ok` y `pendientes_sincronizar`) apenas
arranca, cada `LATIDO_S` (30 s) y enseguida de cada cambio: el enlace se cae o vuelve, se encola algo o se sincroniza
algo. La hora del latido SHALL ser la del reloj de la planta (el último `ts` recibido).

El primer latido SHALL salir apenas arranca el proceso, sin esperar la base, la planta, los modelos ni el índice, que
se cargan en paralelo.

**Razón:** el corrector espera el primer latido hasta 180 s para soltar el reloj del escenario (`sistema_mudo` es
eliminatoria), y mide que los pendientes del latido acompañen al enlace.

#### Scenario: Arranque
- **WHEN** el sistema arranca con los volúmenes vacíos
- **THEN** publica el primer latido antes de terminar de cargar el modelo de voz

#### Scenario: Se cae el enlace
- **WHEN** el enlace se cae
- **THEN** sale un latido con `enlace_ok: false` sin esperar los 30 s

### Requirement: Estado del enlace por sondeo a través del proxy

El sistema SHALL sondear cada `SONDEO_ENLACE_S` (10 s) el `/salud` de la nube a través del proxy `enlace:3128`. El
enlace SHALL considerarse arriba solo si la nube responde 200.

#### Scenario: Proxy que no responde
- **WHEN** el proxy cierra la conexión sin responder
- **THEN** el enlace queda caído

### Requirement: Cola hacia la nube en Postgres, vaciada en orden

Todo lo que va a la nube (alertas de seguridad, escalados con su contexto) SHALL guardarse primero en la tabla
`salida_nube`. Con enlace, el sistema SHALL mandarlo en orden de llegada a `POST /eventos` de la nube por el proxy,
marcando cada envío, y SHALL cortar en el primer error para reintentar después sin saltear ninguno. Sin enlace, todo
SHALL esperar en Postgres. La cola y la nube SHALL usar el id del evento como clave: ni encolar ni recibir dos veces
el mismo id lo duplica.

**Razón:** el corrector mide que lo sincronizado no llegue duplicado (criterio E3) y un reintento puede reenviar un
evento que la nube ya guardó.

#### Scenario: Vuelve el enlace
- **WHEN** hay tres escalados pendientes y vuelve el enlace
- **THEN** llegan a la nube en el orden en que se generaron
- **AND** el latido siguiente muestra 0 pendientes

#### Scenario: Mismo evento dos veces
- **WHEN** se encola dos veces el mismo id de evento, o la nube lo recibe dos veces por un reintento
- **THEN** queda uno solo en la cola y uno solo en la nube

#### Scenario: Reinicio con pendientes
- **WHEN** el sistema se reinicia con pendientes en la cola
- **THEN** los pendientes siguen ahí y se mandan cuando hay enlace

### Requirement: Los servicios de planta no salen por el enlace

Los servicios de planta SHALL salir a internet solo por `HTTP(S)_PROXY=http://enlace:3128`, y `NO_PROXY` SHALL incluir
`broker`, `sim`, `localhost`, `db`, `ollama` y `herramientas`.

**Razón:** sin eso, el cliente HTTP mandaría el LLM local por el proxy y la extracción dejaría de andar justo cuando
se cae el enlace.

#### Scenario: LLM sin enlace
- **WHEN** el enlace está caído y una nota necesita el LLM
- **THEN** la llamada a `ollama` va directo por la LAN de planta
