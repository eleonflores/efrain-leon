"""Extracción del parte por reglas: frases del operador y errores reales de la transcripción."""

from sistema.procesamiento.parte import armar_borrador, preparar_texto
from sistema.procesamiento.reglas_parte import extraer, extraer_con_cobertura


def filas(texto, planta):
    dictado = extraer(preparar_texto(texto), planta)
    assert dictado is not None, texto
    return [(f.tag, f.variable, f.valor, f.unidad) for f in armar_borrador(dictado, planta, [])]


def test_nota_mezclada(planta):
    assert filas("La dos está en ciento doce de descarga, ah, y el filtro B me dio uno ocho de diferencial. "
                 "La tres sigue goteando por la empaquetadura, le saqué foto.", planta) == [
        ("B-102", "presion_descarga_local", 112, "psi"), ("F-201B", "presion_diferencial", 1.8, "kg/cm2"),
        ("B-103", "goteo_empaquetadura", None, "gotas/min")]


def test_nombre_mal_transcripto(planta):
    """Corrida del corrector: "La uno está en…" salió "A uno estar en…"."""
    assert filas("A uno estar en ciento doce kilogramos de descarga el rodamiento, me dio 59 grados con la pistola.",
                 planta) == [("B-101", "presion_descarga_local", 112, "kg/cm2"),
                             ("B-101", "temperatura_rodamiento_ir", 59, "degC")]


def test_lectura_sin_equipo_queda_ambigua_y_no_se_pierde_la_nota(planta):
    dictado, completo = extraer_con_cobertura(preparar_texto("Steinwil 600 psi de descarga. La uno está en 112 de "
                                                             "descarga."), planta)
    assert completo
    borrador = armar_borrador(dictado, planta, [])
    assert borrador[0].tag is None and borrador[0].candidatos == ["B-101", "B-102", "B-103"]
    assert (borrador[1].tag, borrador[1].valor) == ("B-101", 112)


def test_foto_en_la_fila_que_corresponde(planta):
    dictado = extraer(preparar_texto("El filtro B me dio uno seis de diferencial, le saqué foto al manómetro. "
                                     "La dos está en 1640 psi de descarga."), planta)
    borrador = armar_borrador(dictado, planta, ["/media/fotos/manometro_diferencial/01.jpg"])
    assert borrador[0].fotos == ["/media/fotos/manometro_diferencial/01.jpg"] and borrador[1].fotos == []


def test_cada_lectura_toma_el_ultimo_equipo_nombrado_antes(planta):
    """Transcripción real: dos lecturas en la misma cláusula, unidas por "y"."""
    assert filas("La de la punta está en ciento quince kilos de descarga. El pulmón está en cinco metros y el filtro A "
                 "me dio uno con cuatro de diferencial.", planta) == [
        ("B-101", "presion_descarga_local", 115, "kg/cm2"), ("TK-301", "nivel", 5, "m"),
        ("F-201A", "presion_diferencial", 1.4, "kg/cm2")]


def test_numero_mitad_en_palabras_mitad_en_digitos(planta):
    assert filas("La dos está en mil seiscientos 20 psi de descarga.", planta) == [
        ("B-102", "presion_descarga_local", 1620, "psi")]


def test_bomba_sin_articulo_y_unidad_de_otro_manometro_quedan_ambiguas(planta):
    """Corrida del corrector: "También la bomba está en 1600 psi" salió "Ambienta bomba está en…"."""
    dictado = extraer(preparar_texto("La uno está en ciento doce kilogramos de descarga. El rodamiento me dio 59 grados "
                                     "con la pistola. Ambienta bomba está en mil seiscientos psi de descarga. El filtro "
                                     "A me dio uno coma tres de diferencial."), planta)
    borrador = armar_borrador(dictado, planta, [])
    assert [(f.tag, f.valor) for f in borrador] == [("B-101", 112), ("B-101", 59), (None, 1600), ("F-201A", 1.3)]
    assert borrador[2].candidatos == ["B-101", "B-102", "B-103"]


def test_la_unidad_delata_que_no_es_la_bomba_anterior(planta):
    dictado = extraer(preparar_texto("La uno está en 112 kilos de descarga. Está en 1600 psi de descarga."), planta)
    assert [f.equipo for f in dictado.filas] == ["la uno", "la bomba"]
