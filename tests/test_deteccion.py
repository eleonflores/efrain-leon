from datetime import datetime, timedelta

from sistema.dominio.deteccion import MonitorSensores, evaluar_parte


def tipos(decisiones):
    return {d.tag: d.tipo for d in decisiones}


def test_lecturas_normales_son_sin_novedad(planta):
    filas = [
        {"tag": "B-102", "variable": "presion_descarga_local", "valor": 1640, "unidad": "psi"},
        {"tag": "F-201B", "variable": "presion_diferencial", "valor": 1.2, "unidad": "kg/cm2"},
        {"tag": "TK-301", "variable": "nivel", "valor": 5.2, "unidad": "m"},
        {"tag": "B-101", "variable": "temperatura_rodamiento_ir", "valor": 62, "unidad": "degC"},
        {"tag": "B-103", "variable": "estado", "valor": None, "observacion": "parada, en reserva"},
    ]
    assert tipos(evaluar_parte(filas, planta)) == {t: "SinNovedad" for t in ("B-102", "F-201B", "TK-301", "B-101", "B-103")}


def test_observaciones_y_desvios_escalan(planta):
    filas = [
        {"tag": "B-102", "variable": "presion_descarga_local", "valor": 1640, "unidad": "psi"},
        {"tag": "B-102", "variable": "goteo_empaquetadura", "valor": None, "observacion": "gotea"},
        {"tag": "F-201B", "variable": "presion_diferencial", "valor": 1.6, "unidad": "kg/cm2"},
        {"tag": "B-101", "variable": "temperatura_rodamiento_ir", "valor": 79, "unidad": "degC"},
        {"tag": "B-103", "variable": "estado", "valor": None, "observacion": "disparada, no arranca"},
        {"tag": "TK-301", "variable": "nivel", "valor": 7.9, "unidad": "m", "observacion": "está rebalsando a la pileta"},
    ]
    assert tipos(evaluar_parte(filas, planta)) == {t: "Escalado" for t in ("B-102", "F-201B", "B-101", "B-103", "TK-301")}


def test_una_observacion_en_una_lectura_normal_no_escala(planta):
    filas = [{"tag": "B-101", "variable": "presion_descarga_local", "valor": 112, "unidad": "kg/cm2",
              "observacion": "anda bárbaro, revisar más tarde"}]
    assert tipos(evaluar_parte(filas, planta)) == {"B-101": "SinNovedad"}


def test_parte_vacio_es_un_sin_novedad_general(planta):
    assert tipos(evaluar_parte([], planta)) == {None: "SinNovedad"}


def test_desvio_sostenido_de_sensor_escala_una_sola_vez(planta):
    m = MonitorSensores(planta, persistencia=timedelta(minutes=30))
    t0 = datetime(2026, 11, 3, 8, 0)
    assert m.lectura("F-201B", "presion_diferencial", 1.7, t0) is None
    assert m.lectura("F-201B", "presion_diferencial", 1.7, t0 + timedelta(minutes=20)) is None
    d = m.lectura("F-201B", "presion_diferencial", 1.8, t0 + timedelta(minutes=31))
    assert d is not None and d.tipo == "Escalado"
    assert m.lectura("F-201B", "presion_diferencial", 1.8, t0 + timedelta(minutes=40)) is None


def test_pico_aislado_no_escala(planta):
    m = MonitorSensores(planta, persistencia=timedelta(minutes=30))
    t0 = datetime(2026, 11, 3, 8, 0)
    assert m.lectura("B-101", "vibracion", 8.0, t0) is None
    assert m.lectura("B-101", "vibracion", 3.0, t0 + timedelta(minutes=5)) is None
    assert m.lectura("B-101", "vibracion", 8.0, t0 + timedelta(minutes=40)) is None     # el conteo empieza de nuevo


def test_bomba_parada_no_es_un_desvio_de_la_descarga(planta):
    m = MonitorSensores(planta, persistencia=timedelta(minutes=30))
    t0 = datetime(2026, 11, 3, 8, 0)
    for minutos in (0, 20, 40, 60):
        assert m.lectura("B-103", "presion_descarga", 1.6, t0 + timedelta(minutes=minutos)) is None
    assert m.lectura("B-103", "presion_descarga", None, t0 + timedelta(minutes=80)) is None
