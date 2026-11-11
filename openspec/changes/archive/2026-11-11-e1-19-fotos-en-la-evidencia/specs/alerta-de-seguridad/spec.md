## MODIFIED Requirements

### Requirement: Alerta primero, aviso enseguida, lo demás después

Ante una condición insegura el sistema SHALL, en este orden:

1. publicar en `sistema/eventos` un `AlertaSeguridad` con id `EV-<nota>-SEG`, el equipo nombrado en la nota (si hay)
   y los códigos detectados;
2. publicar en `sistema/tablet` el aviso `TAB-<nota>-SEG` con `espera_respuesta: false`, el procedimiento de
   emergencia (alejarse, no intervenir solo, avisar por radio al supervisor) y una fila con la condición;
3. guardar el evento con su evidencia, disparar el latido y encolar la alerta hacia la nube con el contenido de las
   fotos de la nota (como el `Escalado`).

La nota SHALL terminar ahí: SHALL NOT generar borrador de parte.

**Razón:** la alerta es lo que no puede faltar. En una corrida, el aviso y la persistencia antes de la alerta la
demoraron; publicada primero, salió 4 s después de la nota con el enlace caído. Las fotos se buscan después de
publicar, así que no la demoran.

#### Scenario: Nota insegura con el enlace caído
- **WHEN** llega una nota S1 con una foto y el enlace con la nube está caído
- **THEN** el `AlertaSeguridad` y el aviso salen en menos de 30 s reales desde que llegó la nota
- **AND** la alerta queda en la cola hacia la nube, con el contenido de la foto, hasta que vuelva el enlace

#### Scenario: Nota normal
- **WHEN** llega una nota de recorrida sin condiciones inseguras
- **THEN** no se publica ningún `AlertaSeguridad`
