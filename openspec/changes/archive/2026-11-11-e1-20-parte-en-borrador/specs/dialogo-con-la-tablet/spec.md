## ADDED Requirements

### Requirement: El parte pasa de Borrador a Confirmado

Cada vez que sale un borrador a la tablet, el sistema SHALL guardar el parte de la nota en la tabla `partes` con
estado `Borrador` y las filas que se muestran. Cuando el operador confirma, el mismo parte SHALL pasar a `Confirmado`,
con las filas finales y la hora de confirmación; solo un parte `Confirmado` SHALL generar eventos. Un parte sin
valores (solo observaciones, como "parada, en reserva") o una nota sin contenido SHALL guardarse directo como
`Confirmado`, porque no hay nada que confirmar. Un parte que llega al tope de borradores SHALL quedar en `Borrador`.

**Razón:** el enunciado define los estados del parte (Borrador: armado desde las notas, sin confirmar; Confirmado: el
operador lo validó y recién entonces genera eventos) y el anexo pide que el parte pase de Borrador a Confirmado. La
tabla `partes` recibía solo el parte confirmado: el borrador vivía en la conversación de la nota.

#### Scenario: Borrador corregido y confirmado
- **WHEN** sale el borrador B1 de una nota y el operador corrige un valor
- **THEN** el parte está en `partes` como `Borrador` con las filas del borrador B2
- **AND** cuando el operador confirma, pasa a `Confirmado` y recién ahí se publican sus eventos

#### Scenario: Operador que no confirma
- **WHEN** el operador responde tres borradores sin confirmar ninguno
- **THEN** el parte queda como `Borrador` y no se publican eventos de su parte

#### Scenario: Enlace caído
- **WHEN** el enlace está caído durante el diálogo
- **THEN** el parte pasa igual de `Borrador` a `Confirmado`: la base está en la planta
