# deteccion-en-planta Specification

## Purpose

Decidir en código determinístico, con un parte confirmado o con los sensores conectados, si cada equipo está
`SinNovedad` o hay que escalarlo, y dejar lo escalado con su contexto en la cola hacia la nube. Con los mismos datos,
la misma decisión.

## Requirements

### Requirement: Un evento por equipo de cada parte confirmado

Al confirmarse un parte, el sistema SHALL publicar en `sistema/eventos` un `EventoSistema` por equipo, en el orden del
parte, con id `EV-<nota>-<TAG>`, `origen: parte` y `nota_ids`. Un parte sin filas SHALL dar un `SinNovedad` general
`EV-<nota>`, salvo las notas en vivo (`VIVO-…`). La decisión SHALL tomarse por el tipo de variable y los límites,
nunca por el texto libre de la observación, y SHALL NOT usar un LLM.

**Razón:** una frase del modelo no puede inventar ni tapar una anomalía. Los ids derivados de la nota hacen que
reprocesar una nota no duplique eventos.

#### Scenario: Parte mixto
- **WHEN** se confirma "B-102 1640 psi, goteo por empaquetadura; F-201A 1,5 de diferencial"
- **THEN** se publican `EV-<nota>-B-102` `Escalado` (goteo) y `EV-<nota>-F-201A` `Escalado` (1,5 ≥ alarma alta)

### Requirement: Qué escala

Un equipo SHALL quedar `Escalado` si alguna de sus filas cumple una de estas condiciones, y `SinNovedad` si no:

| Fila | Escala cuando |
|---|---|
| Goteo de empaquetadura, aceite bajo en el visor, correas, ruido | Siempre (son observaciones de anomalía) |
| Estado | Disparada, no arranca, falla o trabada. "Parada, en reserva" y "parada por mantenimiento" no escalan |
| Nivel del pulmón | Está rebalsando |
| Temperatura IR del rodamiento | Más de 75 °C |
| Temperatura IR del motor | Más de 65 °C |
| Presión de descarga o diferencial | Fuera de los límites de alarma de la hoja de datos, convertida a kg/cm² |

Los límites SHALL salir de `GET /api/planta` (hoja de datos vigente), nunca del manual Rev. C.

**Razón:** según el TX350-D §3.2 el rodamiento normal anda en 50–70 °C (alarma > 85) y la carcasa del motor en
40–60 °C (alarma > 80). Se escala con 5 °C de margen sobre el máximo normal, por la precisión de la pistola IR, antes
de llegar a la alarma.

#### Scenario: Bomba en reserva
- **WHEN** se confirma "B-103 parada, en reserva; B-101 110 kg/cm²"
- **THEN** los dos equipos quedan `SinNovedad`

#### Scenario: Presión en otra unidad
- **WHEN** la lectura de B-102 es 1640 psi
- **THEN** se compara contra los límites como 115,3 kg/cm²

### Requirement: Los sensores escalan solo con desvíos sostenidos

El sistema SHALL escalar un sensor conectado cuando su valor queda fuera de los límites de alarma durante 30 minutos
de tiempo simulado (medidos con el `ts` de cada lectura), una sola vez por desvío, con id
`EV-SEN-<TAG>-<variable>-<inicio>`. Volver al rango o quedarse sin dato SHALL reiniciar el seguimiento. Una presión de
descarga menor a 30 kg/cm² SHALL tomarse como bomba parada, no como desvío.

**Razón:** la planta publica una muestra por tick real, así que contar muestras daría otra duración a otra velocidad
de simulación. Una bomba parada no publica nulo: su descarga cae a ~1,6 kg/cm², por debajo de la alarma baja de 95.

#### Scenario: Pico aislado
- **WHEN** la vibración de B-101 supera la alarma 10 minutos y vuelve al rango
- **THEN** no se publica ningún evento

#### Scenario: Bomba en reserva
- **WHEN** la descarga de B-103 marca 1,6 kg/cm² durante horas
- **THEN** no se publica ningún evento

### Requirement: Lo escalado va con su contexto a la nube

Cada `Escalado` SHALL guardarse y encolarse hacia la nube con su contexto: las filas del parte de ese equipo, sus
fotos y la tendencia de sus sensores en las 6 horas anteriores (mínimo, máximo, primero, último y cantidad de
muestras).

#### Scenario: Escalado con enlace caído
- **WHEN** se escala B-102 con el enlace caído
- **THEN** el evento sale igual por MQTT y el contexto queda en la cola hasta que vuelva el enlace

### Requirement: El rango histórico avisa lo raro

Para las lecturas con sensor equivalente (descarga y diferencial), el sistema SHALL calcular el rango de operación de
los últimos 45 días del historiador (percentiles 1 y 99, con 3 % de margen, sin las muestras de bomba parada, con al
menos 60 muestras), recalcularlo cada 6 horas de planta y avisar en el borrador cuando una lectura cae afuera. Si el
historiador no responde, SHALL usar el último rango calculado o no avisar.

#### Scenario: Lectura fuera de rango
- **WHEN** el operador dicta para B-101 un valor por debajo del percentil 1 de los últimos 45 días
- **THEN** el borrador dice "Ojo: … fuera del rango de los últimos 45 días" y pide confirmar
