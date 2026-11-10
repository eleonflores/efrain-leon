# alerta-de-seguridad Specification

## Purpose

Detectar en la transcripción de una nota las condiciones inseguras (S1 a S4) y dar la alerta en la tablet y en
`sistema/eventos` en segundos, sin modelos de lenguaje, sin enlace y sin falsas alarmas.

## Requirements

### Requirement: Las condiciones inseguras se detectan por reglas

El sistema SHALL detectar con expresiones regulares sobre la transcripción (sin tildes, en minúsculas) estas
condiciones, y SHALL NOT usar un LLM para hacerlo:

| Código | Condición | Ejemplos de lo que la dispara |
|---|---|---|
| S1 | Pérdida con proyección de agua a presión | "agua a presión", "sale agua para todos lados", "se rompió algo en la descarga", "reventó un niple" |
| S2 | Olor a gas | "olor a gas", "fuga de gas" |
| S3 | Humo o fuego | "humo", "fuego", "olor a quemado", "llamas" |
| S4 | Persona lesionada | "se golpeó", "se cortó", "está sangrando", "está inconsciente" |

La detección SHALL correr antes que cualquier otro procesamiento de la nota.

**Razón:** una falsa alarma resta puntos y una alarma perdida desaprueba (`sin_alerta_de_seguridad` es
eliminatoria). Una regla se lee, se prueba y se explica; un modelo en CPU además tarda más que los 30 s que hay.

#### Scenario: Agua a presión
- **WHEN** la nota dice "¡Atención! Se rompió algo en la descarga de la uno, sale agua a presión para todos lados"
- **THEN** se detecta S1

#### Scenario: Ruidos y pérdidas normales no son alarma
- **WHEN** la nota dice "la dos hace un golpeteo metálico" o "chorrea por la empaquetadura"
- **THEN** no se detecta ninguna condición insegura

### Requirement: Alerta primero, aviso enseguida, lo demás después

Ante una condición insegura el sistema SHALL, en este orden:

1. publicar en `sistema/eventos` un `AlertaSeguridad` con id `EV-<nota>-SEG`, el equipo nombrado en la nota (si hay)
   y los códigos detectados;
2. publicar en `sistema/tablet` el aviso `TAB-<nota>-SEG` con `espera_respuesta: false`, el procedimiento de
   emergencia (alejarse, no intervenir solo, avisar por radio al supervisor) y una fila con la condición;
3. guardar el evento con su evidencia, disparar el latido y encolar la alerta hacia la nube con las fotos.

La nota SHALL terminar ahí: SHALL NOT generar borrador de parte.

**Razón:** la alerta es lo que no puede faltar. En una corrida, el aviso y la persistencia antes de la alerta la
demoraron; publicada primero, salió 4 s después de la nota con el enlace caído.

#### Scenario: Nota insegura con el enlace caído
- **WHEN** llega una nota S1 y el enlace con la nube está caído
- **THEN** el `AlertaSeguridad` y el aviso salen en menos de 30 s reales desde que llegó la nota
- **AND** la alerta queda en la cola hacia la nube hasta que vuelva el enlace

#### Scenario: Nota normal
- **WHEN** llega una nota de recorrida sin condiciones inseguras
- **THEN** no se publica ningún `AlertaSeguridad`

### Requirement: Nada compite con la alerta por la CPU al arrancar

Al arrancar, el sistema SHALL cargar el LLM en memoria sin hacer inferencia.

**Razón:** un calentamiento con inferencia ocupaba la CPU unos 45 s justo cuando llegaba la primera nota: la
transcripción de la nota insegura pasó a 18,7 s y la nota se perdió (73 puntos en el corrector). Con la carga sin
inferencia, 91,3.

#### Scenario: Nota insegura al arrancar
- **WHEN** la primera nota del escenario es insegura y llega mientras el LLM se está cargando
- **THEN** la transcripción no espera al LLM y la alerta sale en menos de 30 s
