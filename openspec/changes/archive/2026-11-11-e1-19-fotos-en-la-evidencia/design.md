## Context

`NotaRecorrida.fotos` trae direcciones relativas a la planta (`/media/fotos/rotura_descarga/04.jpg`, ~25 KB JPEG). El
sistema las asigna a las filas del parte (`parte._asignar_fotos`) y las pasa tal cual al contexto del `Escalado` y al
payload de la alerta. La nube corre en `planta-control`, fuera de `planta-lan`: solo recibe lo que la planta le manda
por el proxy del enlace.

## Decisions

- **Tabla `fotos` con la dirección como clave:** `url`, `tipo`, `contenido` (`bytea`) y fecha. La planta reutiliza
  fotos entre notas, así que una foto se baja una sola vez.
- **Descarga en segundo plano al llegar la nota:** una tarea por nota, lanzada antes de transcribir, con el mismo
  cliente HTTP del audio (red de planta, sin proxy). Tres intentos con 1 s entre uno y otro. Cada descarga se
  registra como paso `consulta` con herramienta `fotos`, como pide `control-de-ejecucion`.
- **El contenido se agrega al encolar, no al guardar el evento:** el contexto del evento en la base sigue con las
  direcciones (las fotos ya están en `fotos`); el payload de la cola lleva `{url, tipo, contenido_b64}` porque es lo
  que la nube recibe tal cual cuando vuelve el enlace.
- **Si al encolar falta una foto**, se intenta bajar una vez más; si no se puede, va `{url, error}`. El evento no
  espera ni se pierde por una foto.
- **La alerta encola después de publicar**, como ya hacía: buscar las fotos no la demora.
- **Sin tests nuevos:** es I/O sin reglas. Se verifica en vivo con el enlace caído y con el corrector.

## Risks / Trade-offs

- La cola guarda las fotos en base64 (~33 KB cada una). Una nota trae 0 a 2 fotos: es poco para Postgres y para el
  proxy del enlace.
- Una foto que la planta no sirve hace que el `Escalado` llegue sin ella; queda el motivo en el payload y en `pasos`.
