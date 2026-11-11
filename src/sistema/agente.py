"""Sistema de la PC de planta: escucha la planta, arma los partes por voz, detecta y alerta."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from planta_contrato import (EstadoSistema, EventoSistema, FilaParte, LecturaSensor, MensajeTablet, NotaRecorrida,
                             Pantalla, RespuestaOperador, Topicos)

from sistema import metricas
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
METRICAS_S = 10        # el visor da por vencidas las métricas a los 30 s
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
    t0: float = field(default_factory=time.perf_counter)
    respondida: bool = False

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

    async def correr(self) -> None:
        tareas = [self.bus.correr(self.recibir, ["planta/#"]), self.latido(), self.enlace.correr(), self.preparar(),
                  self.sincronizar_nube(), self.publicar_metricas()]
        await asyncio.gather(*tareas)

    async def preparar(self) -> None:
        await self.db.conectar()
        self.db_lista = True
        self._lanzar(self._indice_rag())
        definicion = await self._definicion()
        self.planta = Planta.desde_definicion(definicion)
        self.monitor = MonitorSensores(self.planta)
        self.transcriptor = await asyncio.to_thread(stt.crear, self.cfg.stt_modelo, self.cfg.stt_hilos)
        log.info("Transcripción lista: %s", self.transcriptor.nombre)
        self.listo.set()
        await self.restaurar()
        try:
            log.info("LLM %s cargado en %.1f s", self.llm.nombre, await self.llm.cargar())
        except httpx.HTTPError as e:
            log.warning("No se pudo cargar el LLM %s (%s): la extracción sigue por reglas", self.llm.nombre, e)

    async def _indice_rag(self) -> None:
        from sistema.rag.indice import asegurar_indice
        try:
            log.info("Índice RAG: %s", await asegurar_indice(self.cfg.database_url))
        except Exception:  # noqa: BLE001
            log.exception("No se pudo cargar el índice RAG")

    async def _definicion(self) -> dict:
        while True:
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

    async def procesar_nota(self, nota: dict) -> None:
        estado = EstadoNota(nota, presupuesto=Presupuesto(self.cfg.max_pasos_llm_por_nota, self.cfg.max_tokens_por_nota))
        self.notas[estado.id] = estado
        try:
            async with asyncio.timeout(self.cfg.timeout_nota_s):
                await self.listo.wait()
                await self.db.guardar_nota(nota, "recibida")
                if nota.get("fotos"):
                    self._lanzar(self.bajar_fotos(estado.id, nota["fotos"]))
                texto = await self.transcribir(estado)
                t0 = time.perf_counter()
                condiciones = seguridad.detectar(texto)
                ms = int((time.perf_counter() - t0) * 1000)
                if condiciones:
                    await self.alertar(estado, condiciones)
                await self.db.registrar_paso(estado.id, "seguridad", herramienta="detector_seguridad",
                                             argumentos={"texto": texto}, duracion_ms=ms,
                                             detalle={"condiciones": [c.codigo for c in condiciones]})
                if condiciones:
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
        except Exception:  # noqa: BLE001
            log.exception("Nota %s: error", estado.id)
            await self._abandonar(estado, "error")

    async def transcribir(self, estado: EstadoNota) -> str:
        url = estado.nota.get("audio_url")
        if not url:
            return ""
        t0 = time.perf_counter()
        r = await self.http.get(url)
        r.raise_for_status()
        descarga_ms = int((time.perf_counter() - t0) * 1000)
        audio = stt.wav_a_audio(r.content)
        async with self._turno_stt:
            texto, tokens, dur = await self.transcriptor.transcribir_async(audio)
        estado.transcripcion, estado.fase = texto, "transcrita"
        log.info("Nota %s (%.1f s de audio, %.1f s): %s", estado.id, len(audio) / stt.SR, dur, texto)
        await self.db.actualizar_nota(estado.id, transcripcion=texto, fase="transcrita")
        ms = int(dur * 1000)
        await self.db.registrar_paso(estado.id, "transcripcion", modelo=self.transcriptor.nombre, tokens_salida=tokens,
                                     argumentos={"audio_url": url}, duracion_ms=ms,
                                     detalle={"audio_s": round(len(audio) / stt.SR, 1), "generacion_ms": ms,
                                              "descarga_ms": descarga_ms})
        return texto

    async def extraer(self, estado: EstadoNota) -> None:
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
        await self.marcar_fuera_de_rango(estado.filas, estado.id)

    async def marcar_fuera_de_rango(self, filas: list[FilaBorrador], nota_id: str) -> None:
        for f in filas:
            sensor = SENSOR_DE_LECTURA.get(f.variable)
            if not (sensor and f.tag and f.valor is not None and f.valor_dicho is None):
                continue
            rango = await self.rango_historico(f.tag, sensor, nota_id)
            if rango is None:
                continue
            bajo, alto, _ = rango
            valor = f.valor * A_KG.get(f.unidad or "kg/cm2", 1.0)
            if not bajo <= valor <= alto:
                f.fuera_de_rango = (f"{dialogo._fmt(f.valor)} {dialogo.UNIDAD_VISIBLE.get(f.unidad or '', '')} está "
                                    f"fuera del rango de los últimos 45 días ({bajo:.2f} a {alto:.2f} kg/cm²)")

    async def rango_historico(self, tag: str, sensor: str,
                              nota_id: str | None = None) -> tuple[float, float, datetime] | None:
        """(bajo, alto, calculado_en) del rango normal del sensor; None si no hay historial suficiente."""
        clave = (tag, sensor)
        guardado = self._rangos.get(clave)
        if guardado and self.ahora() - guardado[2] < timedelta(hours=6):
            return guardado
        try:
            serie = await self.consultar_historian(nota_id, tag, sensor)
        except ErrorPlanta:
            return guardado
        minimo = BOMBA_PARADA_KG if sensor == "presion_descarga" else float("-inf")
        valores = sorted(m["valor"] for m in serie if m.get("valor") is not None and m["valor"] > minimo)
        if len(valores) < 60:
            self._rangos[clave] = None
            return None
        bajo, alto = valores[int(0.01 * (len(valores) - 1))], valores[int(0.99 * (len(valores) - 1))]
        self._rangos[clave] = (bajo * 0.97, alto * 1.03, self.ahora())
        return self._rangos[clave]

    async def consultar_historian(self, nota_id: str | None, tag: str, sensor: str, *, desde: datetime | None = None,
                                  hasta: datetime | None = None) -> list[dict]:
        argumentos = {"tag": tag, "sensor": sensor, "desde": desde and desde.isoformat(),
                      "hasta": hasta and hasta.isoformat()}
        t0 = time.perf_counter()
        try:
            serie = await self.api.historian(tag, sensor, desde=desde, hasta=hasta)
        except ErrorPlanta as e:
            await self.db.registrar_paso(nota_id, "consulta", herramienta="historian", argumentos=argumentos,
                                         duracion_ms=int((time.perf_counter() - t0) * 1000), ok=False,
                                         detalle={"error": e.mensaje})
            raise
        await self.db.registrar_paso(nota_id, "consulta", herramienta="historian", argumentos=argumentos,
                                     duracion_ms=int((time.perf_counter() - t0) * 1000),
                                     detalle={"muestras": len(serie)})
        return serie

    async def avanzar(self, estado: EstadoNota) -> None:
        """Manda a la tablet el próximo paso: pregunta por un equipo ambiguo, aviso informativo o borrador."""
        ambigua = next((f for f in estado.filas if f.tag is None and f.candidatos), None)
        if ambigua is not None:
            estado.fase, estado.preguntas = "pregunta", estado.preguntas + 1
            texto, opciones = dialogo.pregunta_equipo(ambigua, self.planta)
            await self.tablet(estado, f"TAB-{estado.id}-P{estado.preguntas}", texto, opciones=opciones,
                              titulo="Pregunta")
        elif not any(f.valor is not None for f in estado.filas):
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
            await self.db.guardar_parte(estado.id, "Borrador", estado.filas_json(), estado.nota.get("ts"))
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
        if not estado.respondida:
            estado.respondida = True
            await self.db.registrar_paso(estado.id, "primer_mensaje", argumentos={"mensaje_id": mensaje_id},
                                         duracion_ms=int((time.perf_counter() - estado.t0) * 1000))

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
            await self.marcar_fuera_de_rango([ambigua], estado.id)
            return await self.avanzar(estado)
        if estado.fase != "borrador":
            return
        i = dialogo.interpretar(r.texto, self.planta)
        if i.tipo == "confirma":
            return await self.confirmar(estado)
        if i.tipo == "corrige":
            estado.filas = dialogo.aplicar(estado.filas, i.correcciones, self.planta)
            await self.marcar_fuera_de_rango(estado.filas, estado.id)
        if estado.intento >= self.cfg.max_intentos_borrador:
            return await self._abandonar(estado, f"sin confirmación después de {estado.intento} borradores")
        await self.avanzar(estado)

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
            contexto = {"parte": parte, "fotos": fotos or [], "tendencia": await self.tendencia(d.tag, ts, parte_id)}
            fotos_nube = await self.fotos_para_la_nube(parte_id, fotos or [])
            await self.db.encolar(evento_id, "escalado", {"evento": evento.model_dump(mode="json"),
                                                          "contexto": contexto | {"fotos": fotos_nube}})
            self.latir_ya.set()
        await self.db.guardar_evento(evento.model_dump(mode="json"), contexto)
        await self.db.registrar_paso(parte_id, "deteccion",
                                     herramienta="evaluar_parte" if origen == "parte" else "monitor_sensores",
                                     argumentos={"evento_id": evento_id, "equipo": d.tag, "filas": parte},
                                     detalle={"tipo": d.tipo, "motivos": d.motivos})
        log.info("Evento %s %s %s: %s", evento_id, d.tipo, d.tag or "", resumen)

    async def bajar_fotos(self, nota_id: str | None, urls: list[str], intentos: int = 3) -> dict[str, str]:
        """Baja y guarda las fotos que falten. Devuelve el error de las que no se pudieron bajar."""
        guardadas = await self.db.fotos_guardadas(urls)
        errores = {}
        for url in (u for u in dict.fromkeys(urls) if u not in guardadas):
            t0 = time.perf_counter()
            for intento in range(1, intentos + 1):
                try:
                    r = await self.http.get(url)
                    r.raise_for_status()
                    tipo = r.headers.get("content-type", "application/octet-stream")
                    await self.db.guardar_foto(url, tipo, r.content)
                    errores.pop(url, None)
                    detalle = {"bytes": len(r.content), "tipo": tipo, "intentos": intento}
                    break
                except Exception as e:  # noqa: BLE001
                    errores[url] = f"{type(e).__name__}: {e}"
                    detalle = {"error": errores[url], "intentos": intento}
                    if intento < intentos:
                        await asyncio.sleep(1)
            await self.db.registrar_paso(nota_id, "consulta", herramienta="fotos", argumentos={"url": url},
                                         duracion_ms=int((time.perf_counter() - t0) * 1000), ok=url not in errores,
                                         detalle=detalle)
        return errores

    async def fotos_para_la_nube(self, nota_id: str | None, urls: list[str]) -> list[dict]:
        if not urls:
            return []
        errores = await self.bajar_fotos(nota_id, urls, intentos=1)
        guardadas = await self.db.fotos_guardadas(urls)
        return [{"url": u, "tipo": guardadas[u]["tipo"],
                 "contenido_b64": base64.b64encode(guardadas[u]["contenido"]).decode()} if u in guardadas
                else {"url": u, "error": errores.get(u, "sin bajar")} for u in urls]

    async def tendencia(self, tag: str | None, ts: datetime, nota_id: str | None, horas: int = 6) -> dict:
        if not tag or tag not in self.planta.equipos:
            return {}
        salida = {}
        for sensor in SENSORES_DE_TENDENCIA.get(self.planta.equipos[tag].tipo, []):
            try:
                serie = await self.consultar_historian(nota_id, tag, sensor, desde=ts - timedelta(hours=horas),
                                                       hasta=ts)
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
        evento = EventoSistema(id=f"EV-{estado.id}-SEG", ts=datetime.fromisoformat(estado.nota["ts"]),
                               tipo="AlertaSeguridad", equipo=tag, origen="parte", parte_id=estado.id,
                               nota_ids=[estado.id], resumen=f"{codigos}: " + "; ".join(c.descripcion for c in condiciones))
        self.bus.publicar(Topicos.EVENTOS, evento)
        await self.tablet(estado, f"TAB-{estado.id}-SEG", texto, titulo="ALERTA DE SEGURIDAD", espera=False,
                          filas=[{"tag": tag or "PLANTA", "variable": "condicion_insegura", "valor": None,
                                  "unidad": None, "observacion": estado.transcripcion[:200]}])
        log.warning("ALERTA DE SEGURIDAD %s en nota %s (%s)", codigos, estado.id, tag)
        await self.db.guardar_evento(evento.model_dump(mode="json"), {"evidencia": [c.evidencia for c in condiciones]})
        self.latir_ya.set()
        fotos_nube = await self.fotos_para_la_nube(estado.id, estado.nota.get("fotos", []))
        await self.db.encolar(evento.id, "alerta_seguridad", {"evento": evento.model_dump(mode="json"),
                                                               "fotos": fotos_nube})
        await self.db.actualizar_nota(estado.id, fase="alerta", seguridad=[vars(c) for c in condiciones])

    async def sin_contenido(self, estado: EstadoNota) -> None:
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
        """Retoma las notas que quedaron abiertas en la base."""
        for n in await self.db.notas_abiertas():
            nota = {"id": n["id"], "ts": n["ts"].isoformat() if n["ts"] else None, "fotos": n["fotos"],
                    "audio_url": n["audio_url"], "recorrida_id": n["recorrida_id"], "operador": n["operador"]}
            if n["fase"] in ("recibida", "transcrita") or not n["borrador"]:
                self._lanzar(self.procesar_nota(nota))
                continue
            estado = EstadoNota(nota, n["transcripcion"] or "", [FilaBorrador(**f) for f in n["borrador"]],
                                intento=n["intento"], respondida=True,
                                presupuesto=Presupuesto(self.cfg.max_pasos_llm_por_nota, self.cfg.max_tokens_por_nota))
            self.notas[estado.id] = estado
            log.info("Retomo la nota %s (%s)", estado.id, n["fase"])
            await self.avanzar(estado)

    async def latido(self) -> None:
        while True:
            pendientes = 0
            if self.db_lista:
                try:
                    pendientes = await self.db.cantidad_pendientes()
                except Exception:  # noqa: BLE001
                    log.exception("No pude leer la base para el latido")
            self.bus.publicar(Topicos.ESTADO, EstadoSistema(ts=self.ahora(), sistema=self.cfg.sistema,
                                                            enlace_ok=self.enlace.ok,
                                                            pendientes_sincronizar=pendientes))
            try:
                await asyncio.wait_for(self.latir_ya.wait(), self.cfg.latido_s)
                await asyncio.sleep(0.5)
            except TimeoutError:
                pass
            self.latir_ya.clear()

    async def publicar_metricas(self) -> None:
        while True:
            await asyncio.sleep(METRICAS_S)
            if not self.db_lista:
                continue
            cargados = [m.nombre for m in (self.transcriptor, self.llm) if m is not None]
            try:
                consumo = metricas.consumo_tokens(await self.db.consumo_por_modelo(), cargados, self.cfg.sistema,
                                                  datetime.now(timezone.utc))
            except Exception:  # noqa: BLE001
                log.exception("No pude leer el consumo de la base")
                continue
            if consumo["modelos"]:
                self.bus.publicar("sistema/metricas", consumo)

    async def sincronizar_nube(self) -> None:
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
