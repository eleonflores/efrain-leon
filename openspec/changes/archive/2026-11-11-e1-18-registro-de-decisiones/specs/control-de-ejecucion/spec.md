## MODIFIED Requirements

### Requirement: Cada paso queda registrado

El sistema SHALL registrar en la tabla `pasos` cada transcripción, detección de seguridad, extracción por reglas,
llamada al LLM, decisión de detección, consulta al historiador y abandono, con nota, etapa, modelo o herramienta,
argumentos, tokens de entrada y salida, costo (cero: todo es local), duración, si salió bien y el detalle del error.

- La transcripción SHALL registrar el audio que bajó y cuánto tardó la descarga, los tokens de texto que generó, los
  segundos de audio y el tiempo de transcribir.
- La llamada al LLM SHALL registrar el tiempo de generación que informa Ollama (`generacion_ms`).
- La detección de seguridad SHALL registrarse en cada nota con las condiciones encontradas, o ninguna. Con una
  condición insegura, SHALL registrarse después de publicar la alerta.
- Cada decisión `SinNovedad`/`Escalado` (por parte, por sensor o por nota sin contenido) SHALL registrarse con el
  evento, el equipo, las filas del parte si las hay y los motivos.
- Cada consulta a la API de la planta hecha para una nota o un evento SHALL registrarse como paso `consulta`, con lo
  pedido, cuánto trajo, la duración y el error si lo hubo. Hoy es el historiador (equipo, sensor, rango y muestras).
  Un rango que sale de la caché no es una consulta, y la descarga del audio va en el paso de transcripción.
- El primer mensaje de cada nota a la tablet SHALL registrarse como paso `primer_mensaje`, con la demora desde que la
  nota llegó al proceso.

**Razón:** el enunciado (F) pide cada decisión con las herramientas llamadas, sus argumentos y el tiempo de cada paso.
Las decisiones del código quedaban solo por su resultado (la alerta en la nota, el motivo en el evento) y las
consultas al historiador no quedaban. La planta reinicia los ids de nota cuando arranca de nuevo, y `notas.creada`
queda de la primera vez que llegó ese id: medir la demora contra esa fecha dio 14.351 s de alerta en la base de la
demo.

#### Scenario: Nota resuelta por reglas
- **WHEN** las reglas resuelven una nota
- **THEN** quedan registradas la transcripción, con sus tokens de texto, la detección de seguridad sin condiciones y
  la extracción por reglas, con 0 tokens

#### Scenario: LLM por timeout
- **WHEN** la llamada al LLM corta por timeout
- **THEN** queda registrada sin tokens, con `ok` falso y el `TimeoutError` en el detalle

#### Scenario: Alerta de seguridad
- **WHEN** una nota insegura da la alerta 6 s después de llegar
- **THEN** queda un paso `primer_mensaje` de 6 s con el id del mensaje `TAB-<nota>-SEG`
- **AND** el paso `seguridad` con la condición S1 queda registrado después de publicar la alerta

#### Scenario: Parte confirmado
- **WHEN** se confirma un parte con B-102 con goteo y F-201A dentro de rango
- **THEN** quedan dos pasos `deteccion`: B-102 `Escalado` con el motivo del goteo y F-201A `SinNovedad`

#### Scenario: Historiador caído
- **WHEN** el historiador no responde al calcular el rango de una lectura
- **THEN** queda un paso `consulta` con `ok` falso y el error, y el borrador sale sin aviso de rango

#### Scenario: Enlace caído
- **WHEN** el enlace está caído
- **THEN** los pasos se registran igual: la base y el historiador están en la red de planta
