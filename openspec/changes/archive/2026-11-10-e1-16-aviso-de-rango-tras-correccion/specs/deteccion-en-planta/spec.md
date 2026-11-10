## MODIFIED Requirements

### Requirement: El rango histórico avisa lo raro

Para las lecturas con sensor equivalente (descarga y diferencial), el sistema SHALL calcular el rango de operación de
los últimos 45 días del historiador (percentiles 1 y 99, con 3 % de margen, sin las muestras de bomba parada, con al
menos 60 muestras), recalcularlo cada 6 horas de planta y avisar en el borrador cuando una lectura cae afuera. Si el
historiador no responde, SHALL usar el último rango calculado o no avisar. Cuando el operador corrige el valor, la
unidad o el equipo de una fila, el aviso de esa fila SHALL recalcularse con lo corregido.

#### Scenario: Lectura fuera de rango
- **WHEN** el operador dicta para B-101 un valor por debajo del percentil 1 de los últimos 45 días
- **THEN** el borrador dice "Ojo: … fuera del rango de los últimos 45 días" y pide confirmar

#### Scenario: Corrección a un valor dentro del rango
- **WHEN** el borrador avisa que B-101 150 kg/cm² está fuera del rango y el operador corrige "la uno estaba en ciento quince kilos, no en ciento cincuenta"
- **THEN** el nuevo borrador muestra B-101 115 kg/cm² sin aviso de rango
