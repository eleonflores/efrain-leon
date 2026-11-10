"""El sistema de la PC de planta: escucha la planta, arma los partes por voz, detecta y alerta.

Recorrido de una nota (ver `docs/spec-parte-por-voz.md`):

    planta/recorridas → audio → transcripción local → ¿condición insegura? → alerta en < 30 s
                                                    → extracción (LLM + reglas) → tablet ⇄ operador
                                                    → parte Confirmado → eventos (SinNovedad / Escalado)
                                                    → lo escalado, a la cola hacia la nube

La recepción de mensajes no espera al procesamiento: cada nota corre en su propia tarea, con un timeout global, y la
CPU se reparte con semáforos (una transcripción y un llamado al LLM por vez).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from planta_contrato import (EstadoSistema, EventoSistema, FilaParte, LecturaSensor, MensajeTablet, NotaRecorrida,
                             Pantalla, RespuestaOperador, Topicos)

from sistema.config import CONFIG, Config
from sistema.dominio.deteccion import BOMBA_PARADA_KG, Decision, MonitorSensores, evaluar_parte
from sistema.dominio.planta import A_KG, SENSOR_DE_LECTURA, Planta
from sistema.integraciones.enlace import Enlace
from sistema.integraciones.planta_api import ClientePlanta, ErrorPlanta
from sistema.integraciones.mqtt import Bus
from sistema.llm.modelo import ModeloLocal, Presupuesto, PresupuestoAgotado
from sistema.persistencia.db import Base
from sistema.procesamiento import dialogo, reglas_parte, seguridad, stt
from sistema.procesamiento.parte import INSTRUCCIONES, Dictado, FilaBorrador, armar_borrador, preparar_texto

log = logging.getLogger("sistema")
SENSORES_DE_TENDENCIA = {"bomba": ["presion_descarga", "vibracion", "temperatura_aceite", "presion_succion"],
                         "filtro": ["presion_diferencial"], "caudalimetro": ["caudal"], "tanque": []}


@dataclass
class EstadoNota:
    nota: dict
    transcripcion: str = ""
    filas: list[FilaBorrador] = field(default_factory=list)
    fase: str = "recibida"        # recibida → transcrita → pregunta / borrador → confirmada | alerta | abandonada
    intento: int = 0               # borradores mostrados
    preguntas: int = 0
    presupuesto: Presupuesto | None = None

    @property
    def id(self) -> str:
        return self.nota["id"]

    def filas_json(self) -> list[dict]:
        return [vars(f) for f in self.filas]


class Sistema:
    def __init__(self, cfg: Config = CONFIG):
        self.cfg = cfg
        self.bus = Bus(cfg.mqtt_host, cfg.mqtt_port, "efrain-leon-planta")
        self.db = Base(cfg.database_url)
        self.enlace = Enlace(cfg.nube_url, cfg.proxy, cfg.sondeo_enlace_s)
        self.http = httpx.AsyncClient(base_url=cfg.planta_url, timeout=20, trust_env=False)   # audios
        self.api = ClientePlanta(cfg.planta_url, timeout_s=15)
        self.llm = ModeloLocal(cfg.ollama_url, cfg.llm_modelo, hilos=cfg.llm_hilos, timeout_s=cfg.llm_timeout_s)
        self.planta: Planta | None = None
        self.monitor: MonitorSensores | None = None
        self.transcriptor: stt.Transcriptor | None = None
        self.listo = asyncio.Event()
        self.db_lista = False
        self.reloj: datetime | None = None
        self.notas: dict[str, EstadoNota] = {}
        self.mensaje_a_nota: dict[str, str] = {}
        self._turno_stt = asyncio.Semaphore(1)
        self.latir_ya = self.enlace.cambio      # el latido sale apenas cambia el enlace o la cola
        self._rangos: dict[tuple[str, str], tuple[float, float, datetime] | None] = {}
        self._tareas: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ arranque

    async def correr(self) -> None:
        tareas = [self.bus.correr(self.recibir, ["planta/#"]), self.latido(), self.enlace.correr(), self.preparar(),
                  self.sincronizar_nube()]
        await asyncio.gather(*tareas)

    async def preparar(self) -> None:
        """Lo lento va después del primer latido: el corrector espera el latido para soltar el reloj."""
        await self.db.conectar()
        self.db_lista = True
        definicion = await self._definicion()
        self.planta = Planta.desde_definicion(definicion)
        self.monitor = MonitorSensores(self.planta)
        self.transcriptor = await asyncio.to_thread(stt.crear, self.cfg.stt_modelo, self.cfg.stt_hilos)
        log.info("Transcripción lista: %s", self.transcriptor.nombre)
        self.listo.set()
        await self.restaurar()
        _, paso = await self.llm.estructurado(INSTRUCCIONES, "<nota>La uno está en 110 de descarga.</nota>", Dictado,
                                              "calentamiento")
        log.info("LLM %s listo en %.1f s", self.llm.nombre, paso.duracion_ms / 1000)

    async def _definicion(self) -> dict:
        while True:                      # la planta puede tardar en arrancar: se espera sin límite
            try:
                return await self.api.definicion()
            except ErrorPlanta as e:
                log.info("Esperando a la planta (%s)", e.mensaje)
                await asyncio.sleep(3)

    def ahora(self) -> datetime:
        return self.reloj or datetime.now(timezone.utc)

    def _lanzar(self, coro) -> None:
        tarea = asyncio.create_task(coro)
        self._tareas.add(tarea)
        tarea.add_done_callback(self._tareas.discard)

    # ------------------------------------------------------------------ mensajes de la planta

    async def recibir(self, topico: str, datos: dict) -> None:
        if topico.startswith("planta/sensores/"):
            self._lectura(datos)
        elif topico == Topicos.RECORRIDAS:
            nota = NotaRecorrida.model_validate(datos)
            self.reloj = nota.ts
            self._lanzar(self.procesar_nota(nota.model_dump(mode="json")))
        elif topico == Topicos.RESPUESTAS:
            self._lanzar(self.procesar_respuesta(RespuestaOperador.model_validate(datos)))
        elif topico == Topicos.ENERGIA:
            log.info("Energía: %s", datos)

    def _lectura(self, datos: dict) -> None:
        try:
            l = LecturaSensor.model_validate(datos)
        except ValueError:
            return
        self.reloj = l.ts
        if self.monitor is None:
            return
        decision = self.monitor.lectura(l.tag, l.variable, l.valor, l.ts)
        if decision:
            desde = self.monitor.inicio_del_desvio(l.tag, l.variable) or l.ts
            evento_id = f"EV-SEN-{l.tag}-{l.variable}-{desde:%Y%m%dT%H%M}"
            self._lanzar(self.publicar_evento(evento_id, decision, "sensor", [], None, l.ts))

    # ------------------------------------------------------------------ una nota

    async def procesar_nota(self, nota: dict) -> None:
        estado = EstadoNota(nota, presupuesto=Presupuesto(self.cfg.max_pasos_llm_por_nota, self.cfg.max_tokens_por_nota))
        self.notas[estado.id] = estado
        try:
            async with asyncio.timeout(self.cfg.timeout_nota_s):
                await self.listo.wait()
                await self.db.guardar_nota(nota, "recibida")
                texto = await self.transcribir(estado)
                condiciones = seguridad.detectar(texto)
                if condiciones:
                    await self.alertar(estado, condiciones)
                    return
                await self.extraer(estado)
                if not any(f.valor is not None or f.observacion for f in estado.filas):
                    await self.sin_contenido(estado)
                    return
                await self.avanzar(estado)
        except TimeoutError:
            log.error("Nota %s: se agotó el timeout global de %.0f s", estado.id, self.cfg.timeout_nota_s)
            await self._abandonar(estado, "timeout global")
        except PresupuestoAgotado as e:
            log.error("Nota %s: presupuesto agotado (%s)", estado.id, e)
            await self._abandonar(estado, f"presupuesto agotado: {e}")
        except Exception:  # noqa: BLE001  una nota rota no tumba el sistema
            log.exception("Nota %s: error", estado.id)
            await self._abandonar(estado, "error")

    async def transcribir(self, estado: EstadoNota) -> str:
        url = estado.nota.get("audio_url")
        if not url:
            return ""
        r = await self.http.get(url)
        r.raise_for_status()
        audio = stt.wav_a_audio(r.content)
        async with self._turno_stt:
            texto, dur = await self.transcriptor.transcribir_async(audio)
        estado.transcripcion, estado.fase = texto, "transcrita"
        log.info("Nota %s (%.1f s de audio, %.1f s): %s", estado.id, len(audio) / stt.SR, dur, texto)
        await self.db.actualizar_nota(estado.id, transcripcion=texto, fase="transcrita")
        await self.db.registrar_paso(estado.id, "transcripcion", modelo=self.transcriptor.nombre,
                                     duracion_ms=int(dur * 1000), detalle={"audio_s": round(len(audio) / stt.SR, 1)})
        return texto

    async def extraer(self, estado: EstadoNota) -> None:
        """Primero las reglas (milisegundos, el dictado típico); si no explican la nota, el LLM local."""
        texto = preparar_texto(estado.transcripcion)
        t0 = time.perf_counter()
        dictado, completo = reglas_parte.extraer_con_cobertura(texto, self.planta)
        await self.db.registrar_paso(estado.id, "extraccion_reglas", herramienta="reglas_parte",
                                     argumentos={"texto": texto}, ok=completo,
                                     duracion_ms=int((time.perf_counter() - t0) * 1000),
                                     detalle=None if completo else {"parcial": dictado is not None})
        if not completo:
            del_llm, paso = await self.llm.estructurado(INSTRUCCIONES, f"<nota>{texto}</nota>", Dictado,
                                                        "extraccion_llm", estado.presupuesto)
            await self.db.registrar_paso(estado.id, paso.etapa, modelo=paso.modelo, tokens_entrada=paso.tokens_entrada,
                                         tokens_salida=paso.tokens_salida, duracion_ms=paso.duracion_ms, ok=paso.ok,
                                         argumentos={"texto": texto}, detalle=paso.detalle or None)
            if del_llm is not None and del_llm.filas:
                dictado = del_llm
            elif dictado is not None:
                log.info("Nota %s: el LLM no resolvió; va el borrador parcial de las reglas", estado.id)
        estado.filas = armar_borrador(dictado, self.planta, estado.nota.get("fotos", [])) if dictado else []
        await self.marcar_fuera_de_rango(estado.filas)

    # ------------------------------------------------------------------ rango histórico

    async def marcar_fuera_de_rango(self, filas: list[FilaBorrador]) -> None:
        for f in filas:
            sensor = SENSOR_DE_LECTURA.get(f.variable)
            if not (sensor and f.tag and f.valor is not None and f.valor_dicho is None):
                continue
            rango = await self.rango_historico(f.tag, sensor)
            if rango is None:
                continue
            bajo, alto, _ = rango
            valor = f.valor * A_KG.get(f.unidad or "kg/cm2", 1.0)
            if not bajo <= valor <= alto:
                f.fuera_de_rango = (f"{dialogo._fmt(f.valor)} {dialogo.UNIDAD_VISIBLE.get(f.unidad or '', '')} está "
                                    f"fuera del rango de los últimos 45 días ({bajo:.2f} a {alto:.2f} kg/cm²)")

    async def rango_historico(self, tag: str, sensor: str) -> tuple[float, float, datetime] | None:
        """Percentiles 1 y 99 del historiador (45 días) con un 3 % de margen; se recalcula cada 6 h de planta."""
        clave = (tag, sensor)
        guardado = self._rangos.get(clave)
        if guardado and self.ahora() - guardado[2] < timedelta(hours=6):
            return guardado
        try:
            serie = await self.api.historian(tag, sensor)
        except ErrorPlanta:
            return guardado
        # Con la bomba parada la descarga marca ~1,6 kg/cm²: esas muestras no son del rango de operación.
        minimo = BOMBA_PARADA_KG if sensor == "presion_descarga" else float("-inf")
        valores = sorted(m["valor"] for m in serie if m.get("valor") is not None and m["valor"] > minimo)
        if len(valores) < 60:
            self._rangos[clave] = None
            return None
        bajo, alto = valores[int(0.01 * (len(valores) - 1))], valores[int(0.99 * (len(valores) - 1))]
        self._rangos[clave] = (bajo * 0.97, alto * 1.03, self.ahora())
        return self._rangos[clave]

    # ------------------------------------------------------------------ tablet

    async def avanzar(self, estado: EstadoNota) -> None:
        """Manda lo que corresponda: una pregunta por el próximo equipo ambiguo o el borrador."""
        ambigua = next((f for f in estado.filas if f.tag is None and f.candidatos), None)
        if ambigua is not None:
            estado.fase, estado.preguntas = "pregunta", estado.preguntas + 1
            texto, opciones = dialogo.pregunta_equipo(ambigua, self.planta)
            await self.tablet(estado, f"TAB-{estado.id}-P{estado.preguntas}", texto, opciones=opciones,
                              titulo="Pregunta")
        elif not any(f.valor is not None for f in estado.filas):
            # Solo estados u observaciones ("la tres está parada, en reserva"): el operador compara valores, así que
            # no hay nada que confirmar. Se le informa sin pedir respuesta y el parte queda confirmado.
            await self.tablet(estado, f"TAB-{estado.id}-I", dialogo.texto_borrador(estado.filas, self.planta)
                              .replace(" ¿Lo confirmás?", " Lo registro así."),
                              filas=[f.a_fila_parte() for f in estado.filas if f.tag],
                              titulo="Parte de recorrida", espera=False)
            await self.confirmar(estado)
            return
        else:
            estado.fase, estado.intento = "borrador", estado.intento + 1
            await self.tablet(estado, f"TAB-{estado.id}-B{estado.intento}",
                              dialogo.texto_borrador(estado.filas, self.planta),
                              filas=[f.a_fila_parte() for f in estado.filas if f.tag],
                              opciones=dialogo.opciones_de_valor(estado.filas),
                              titulo="Parte de recorrida · borrador")
        await self.db.actualizar_nota(estado.id, fase=estado.fase, intento=estado.intento, borrador=estado.filas_json())

    async def tablet(self, estado: EstadoNota, mensaje_id: str, texto: str, *, filas: list[dict] | None = None,
                     opciones: list[str] | None = None, titulo: str | None = None, espera: bool = True) -> None:
        mensaje = MensajeTablet(id=mensaje_id, ts=self.ahora(), nota_ids=[estado.id], texto=texto,
                                pantalla=Pantalla(titulo=titulo, filas=[FilaParte(**f) for f in (filas or [])],
                                                  opciones=opciones or []),
                                espera_respuesta=espera)
        self.mensaje_a_nota[mensaje_id] = estado.id
        self.bus.publicar(Topicos.TABLET, mensaje)
        await self.db.guardar_mensaje(estado.id, mensaje.model_dump(mode="json"))

    async def procesar_respuesta(self, r: RespuestaOperador) -> None:
        nota_id = self.mensaje_a_nota.get(r.mensaje_id) or await self.db.guardar_respuesta(r.mensaje_id, {})
        estado = self.notas.get(nota_id) if nota_id else None
        if estado is None:
            return
        await self.db.guardar_respuesta(r.mensaje_id, r.model_dump(mode="json"))
        log.info("Nota %s · operador: %s", estado.id, r.texto)
        if estado.fase == "pregunta":
            ambigua = next(f for f in estado.filas if f.tag is None and f.candidatos)
            i = dialogo.interpretar(r.texto, self.planta, candidatos=ambigua.candidatos)
            if i.elegido is None and estado.preguntas < 2:
                return await self.avanzar(estado)
            ambigua.tag = i.elegido or ambigua.candidatos[0]
            ambigua.unidad = ambigua.unidad or self.planta.unidad_por_defecto(ambigua.tag, ambigua.variable)
            ambigua.candidatos = []
            await self.marcar_fuera_de_rango([ambigua])
            return await self.avanzar(estado)
        if estado.fase != "borrador":
            return
        i = dialogo.interpretar(r.texto, self.planta)
        if i.tipo == "confirma":
            return await self.confirmar(estado)
        if i.tipo == "corrige":
            estado.filas = dialogo.aplicar(estado.filas, i.correcciones, self.planta)
        if estado.intento >= self.cfg.max_intentos_borrador:
            return await self._abandonar(estado, f"sin confirmación después de {estado.intento} borradores")
        await self.avanzar(estado)

    # ------------------------------------------------------------------ resultados

    async def confirmar(self, estado: EstadoNota) -> None:
        estado.fase = "confirmada"
        filas = [f.a_fila_parte() for f in estado.filas if f.tag]
        await self.db.guardar_parte(estado.id, "Confirmado", estado.filas_json(), estado.nota.get("ts"))
        await self.db.actualizar_nota(estado.id, fase="confirmada", borrador=estado.filas_json())
        ts = datetime.fromisoformat(estado.nota["ts"])
        for d in evaluar_parte(filas, self.planta):
            evento_id = f"EV-{estado.id}" + (f"-{d.tag}" if d.tag else "")
            fotos = [foto for f in estado.filas if f.tag == d.tag for foto in f.fotos]
            await self.publicar_evento(evento_id, d, "parte", [estado.id], estado.id, ts, fotos=fotos,
                                       parte=[f for f in filas if f["tag"] == d.tag])
        await self.tablet(estado, f"TAB-{estado.id}-OK", "Listo, guardé el parte. Gracias.", espera=False)

    async def publicar_evento(self, evento_id: str, d: Decision, origen: str, nota_ids: list[str],
                              parte_id: str | None, ts: datetime, *, fotos: list[str] | None = None,
                              parte: list[dict] | None = None) -> None:
        resumen = "; ".join(d.motivos) if d.motivos else "Valores dentro de rango"
        evento = EventoSistema(id=evento_id, ts=ts, tipo=d.tipo, equipo=d.tag, origen=origen, parte_id=parte_id,
                               nota_ids=nota_ids, resumen=resumen[:300])
        self.bus.publicar(Topicos.EVENTOS, evento)
        contexto = None
        if d.tipo == "Escalado":
            contexto = {"parte": parte, "fotos": fotos or [], "tendencia": await self.tendencia(d.tag, ts)}
            await self.db.encolar(evento_id, "escalado", {"evento": evento.model_dump(mode="json"), "contexto": contexto})
            self.latir_ya.set()
        await self.db.guardar_evento(evento.model_dump(mode="json"), contexto)
        log.info("Evento %s %s %s: %s", evento_id, d.tipo, d.tag or "", resumen)

    async def tendencia(self, tag: str | None, ts: datetime, horas: int = 6) -> dict:
        """Resumen de los sensores del equipo en las últimas horas (contexto del escalado)."""
        if not tag or tag not in self.planta.equipos:
            return {}
        salida = {}
        for sensor in SENSORES_DE_TENDENCIA.get(self.planta.equipos[tag].tipo, []):
            try:
                serie = await self.api.historian(tag, sensor, desde=ts - timedelta(hours=horas), hasta=ts)
            except ErrorPlanta:
                continue
            valores = [m["valor"] for m in serie if m.get("valor") is not None]
            if valores:
                salida[sensor] = {"min": round(min(valores), 2), "max": round(max(valores), 2),
                                  "primero": round(valores[0], 2), "ultimo": round(valores[-1], 2), "n": len(valores)}
        return salida

    async def alertar(self, estado: EstadoNota, condiciones: list[seguridad.Condicion]) -> None:
        estado.fase = "alerta"
        equipos = self.planta.equipos_en_texto(estado.transcripcion)
        tag = equipos[0] if equipos else None
        codigos = ", ".join(c.codigo for c in condiciones)
        texto = seguridad.mensaje_emergencia(condiciones, dialogo.nombre_de(self.planta, tag) if tag else None)
        await self.tablet(estado, f"TAB-{estado.id}-SEG", texto, titulo="ALERTA DE SEGURIDAD", espera=False,
                          filas=[{"tag": tag or "PLANTA", "variable": "condicion_insegura", "valor": None,
                                  "unidad": None, "observacion": estado.transcripcion[:200]}])
        evento = EventoSistema(id=f"EV-{estado.id}-SEG", ts=datetime.fromisoformat(estado.nota["ts"]),
                               tipo="AlertaSeguridad", equipo=tag, origen="parte", parte_id=estado.id,
                               nota_ids=[estado.id], resumen=f"{codigos}: " + "; ".join(c.descripcion for c in condiciones))
        self.bus.publicar(Topicos.EVENTOS, evento)
        log.warning("ALERTA DE SEGURIDAD %s en nota %s (%s)", codigos, estado.id, tag)
        await self.db.guardar_evento(evento.model_dump(mode="json"), {"evidencia": [c.evidencia for c in condiciones]})
        self.latir_ya.set()
        await self.db.encolar(evento.id, "alerta_seguridad", {"evento": evento.model_dump(mode="json"),
                                                               "fotos": estado.nota.get("fotos", [])})
        await self.db.actualizar_nota(estado.id, fase="alerta", seguridad=[vars(c) for c in condiciones])

    async def sin_contenido(self, estado: EstadoNota) -> None:
        """Una nota sin lecturas (p. ej. "recorrida sin novedad"): se avisa y queda un SinNovedad general."""
        estado.fase = "confirmada"
        await self.tablet(estado, f"TAB-{estado.id}-OK", "No encontré lecturas para cargar en esta nota; la registré "
                          "como recorrida sin novedad.", espera=False,
                          filas=[{"tag": "PLANTA", "variable": "recorrida", "valor": None, "unidad": None,
                                  "observacion": "sin novedad"}])
        await self.db.guardar_parte(estado.id, "Confirmado", [], estado.nota.get("ts"))
        await self.db.actualizar_nota(estado.id, fase="sin_contenido")
        if not estado.id.startswith("VIVO-"):
            await self.publicar_evento(f"EV-{estado.id}", Decision(None, "SinNovedad"), "parte", [estado.id], estado.id,
                                       datetime.fromisoformat(estado.nota["ts"]))

    async def _abandonar(self, estado: EstadoNota, motivo: str) -> None:
        estado.fase = "abandonada"
        await self.db.registrar_paso(estado.id, "abandono", ok=False, detalle={"motivo": motivo})
        if self.db_lista:
            await self.db.actualizar_nota(estado.id, fase="abandonada")

    async def restaurar(self) -> None:
        """Después de un reinicio: retoma los diálogos abiertos mandando de nuevo el último paso."""
        for n in await self.db.notas_abiertas():
            nota = {"id": n["id"], "ts": n["ts"].isoformat() if n["ts"] else None, "fotos": n["fotos"],
                    "audio_url": n["audio_url"], "recorrida_id": n["recorrida_id"], "operador": n["operador"]}
            if n["fase"] in ("recibida", "transcrita") or not n["borrador"]:
                self._lanzar(self.procesar_nota(nota))
                continue
            estado = EstadoNota(nota, n["transcripcion"] or "", [FilaBorrador(**f) for f in n["borrador"]],
                                intento=n["intento"],
                                presupuesto=Presupuesto(self.cfg.max_pasos_llm_por_nota, self.cfg.max_tokens_por_nota))
            self.notas[estado.id] = estado
            log.info("Retomo la nota %s (%s)", estado.id, n["fase"])
            await self.avanzar(estado)

    # ------------------------------------------------------------------ latido y nube

    async def latido(self) -> None:
        vuelta = 0
        while True:
            pendientes = 0
            if self.db_lista:
                try:
                    pendientes = await self.db.cantidad_pendientes()
                    if vuelta % 2 == 0:
                        await self.publicar_consumo()
                except Exception:  # noqa: BLE001
                    log.exception("No pude leer la base para el latido")
            self.bus.publicar(Topicos.ESTADO, EstadoSistema(ts=self.ahora(), sistema=self.cfg.sistema,
                                                            enlace_ok=self.enlace.ok,
                                                            pendientes_sincronizar=pendientes))
            vuelta += 1
            try:
                await asyncio.wait_for(self.latir_ya.wait(), self.cfg.latido_s)
                await asyncio.sleep(0.5)        # que termine de escribirse lo que lo disparó
            except TimeoutError:
                pass
            self.latir_ya.clear()

    async def publicar_consumo(self) -> None:
        """Tokens acumulados por modelo en `sistema/metricas` (telemetría opcional que muestra el visor). Respeta el
        validador de la planta: totales = suma del desglose, un modelo por fila, fecha con zona horaria."""
        modelos = [m for m in await self.db.consumo_por_modelo() if (m["entrada"] or 0) + (m["salida"] or 0) > 0]
        if not modelos:
            return
        filas = [{"modelo": m["modelo"], "tokens_entrada": int(m["entrada"]), "tokens_salida": int(m["salida"]),
                  "tokens_total": int(m["entrada"]) + int(m["salida"]),
                  "tokens_por_segundo": round(int(m["salida"]) / (m["ms"] / 1000), 2) if m["ms"] else None,
                  "velocidad_estimada": False} for m in modelos]
        entrada, salida = sum(f["tokens_entrada"] for f in filas), sum(f["tokens_salida"] for f in filas)
        ms = sum(m["ms"] or 0 for m in modelos)
        self.bus.publicar("sistema/metricas", {
            "ts": datetime.now(timezone.utc).isoformat(), "sistema": self.cfg.sistema, "tokens_entrada": entrada,
            "tokens_salida": salida, "tokens_total": entrada + salida,
            "tokens_por_segundo": round(salida / (ms / 1000), 2) if ms else None, "velocidad_estimada": False,
            "modelos": filas})

    async def sincronizar_nube(self) -> None:
        """Vacía la cola hacia la nube en orden cuando hay enlace. Sin enlace, todo espera en Postgres."""
        while True:
            await asyncio.sleep(5)
            if not (self.db_lista and self.enlace.ok):
                continue
            try:
                async with httpx.AsyncClient(proxy=self.cfg.proxy, timeout=10) as http:
                    for p in await self.db.pendientes():
                        r = await http.post(f"{self.cfg.nube_url}/eventos", json={"id": p["id"], "tipo": p["tipo"],
                                                                                   "payload": p["payload"]})
                        r.raise_for_status()
                        await self.db.marcar_enviado(p["id"])
                        self.latir_ya.set()
            except httpx.HTTPError as e:
                log.info("No se pudo sincronizar con la nube: %s", e)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(Sistema().correr())


if __name__ == "__main__":
    main()
