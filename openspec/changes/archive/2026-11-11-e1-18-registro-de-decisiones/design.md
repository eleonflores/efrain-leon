## Context

`Base.registrar_paso` guarda nota, etapa, modelo o herramienta, argumentos, tokens, costo, duración, ok y detalle. Las
decisiones de detección pasan todas por `Sistema.publicar_evento` (parte confirmado, desvío de sensor y nota sin
contenido). Las consultas al historiador salen de `rango_historico` (rango de 45 días, en caché 6 h de planta) y de
`tendencia` (6 h antes del evento).

## Decisions

- **Etapas nuevas:** `seguridad` (herramienta `detector_seguridad`), `deteccion` (herramienta `evaluar_parte` o
  `monitor_sensores`, según el origen) y `consulta` (herramienta `historian`).
- **La decisión se registra en `publicar_evento`:** es el único lugar por donde pasan las tres fuentes de eventos, con
  el equipo, el id del evento, las filas del parte (si las hay) y los motivos.
- **El historiador se consulta por un solo método del agente** (`consultar_historian`), que mide y registra éxito o
  error. Una consulta que sale de la caché no es una consulta y no se registra.
- **La nota viaja como argumento** hasta `rango_historico`, `marcar_fuera_de_rango` y `tendencia`. Un desvío de
  sensor no tiene nota: su paso queda con `nota_id` nulo.
- **La alerta primero:** con condiciones inseguras, el paso `seguridad` se registra después de `alertar`.
- **La descarga del audio va en el paso de transcripción** (`argumentos.audio_url`, `detalle.descarga_ms`), sin una
  etapa aparte.
- **Sin tests nuevos:** es registro de I/O, sin reglas. Se verifica en vivo y con el corrector.

## Risks / Trade-offs

- Más filas en `pasos`: una nota típica suma 1 de seguridad, 1 a 3 consultas y una decisión por equipo. Es poco para
  Postgres y el corrector borra la base entre escenarios.
