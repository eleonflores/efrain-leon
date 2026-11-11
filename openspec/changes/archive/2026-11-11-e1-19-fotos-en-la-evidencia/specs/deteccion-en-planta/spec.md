## ADDED Requirements

### Requirement: Las fotos se bajan al llegar la nota

El sistema SHALL bajar las fotos de cada nota de `http://sim:8100{url}` apenas llega la nota, en una tarea aparte que
no demore la transcripción ni la alerta, con hasta tres intentos, y guardarlas en la base. Una foto ya guardada SHALL
NOT bajarse de nuevo.

**Razón:** el anexo de la Entrega 1 pide bajar el audio y las fotos. La nube está fuera de la red de planta y no puede
abrir `http://sim:8100`: si recibe solo la dirección, el `Escalado` llega sin la evidencia.

#### Scenario: Nota con foto y el enlace caído
- **WHEN** llega una nota con una foto y el enlace con la nube está caído
- **THEN** la foto se baja igual, por la red de planta, y queda guardada en la base

#### Scenario: Foto repetida
- **WHEN** dos notas traen la misma foto
- **THEN** la foto se baja una sola vez

## MODIFIED Requirements

### Requirement: Lo escalado va con su contexto a la nube

Cada `Escalado` SHALL guardarse y encolarse hacia la nube con su contexto: las filas del parte de ese equipo, sus
fotos y la tendencia de sus sensores en las 6 horas anteriores (mínimo, máximo, primero, último y cantidad de
muestras). En la cola, cada foto SHALL ir con su contenido (tipo y base64); una foto que no se pudo bajar SHALL ir con
su dirección y el motivo, sin frenar el evento.

#### Scenario: Escalado con enlace caído
- **WHEN** se escala B-102 con el enlace caído
- **THEN** el evento sale igual por MQTT y el contexto queda en la cola hasta que vuelva el enlace
- **AND** cuando vuelve el enlace, la nube recibe el contenido de las fotos de B-102

#### Scenario: Foto que no se pudo bajar
- **WHEN** la planta no sirve una foto de un equipo escalado
- **THEN** el `Escalado` se encola igual, con la dirección de esa foto y el motivo
