import pytest

from sistema.procesamiento.dialogo import aplicar, interpretar, opciones_de_valor, pregunta_equipo, texto_borrador
from sistema.procesamiento.parte import FilaBorrador


@pytest.mark.parametrize("texto", ["Sí, confirmo.", "Está bien, confirmo.", "Correcto, dale.", "Perfecto, confirmo."])
def test_confirmaciones(planta, texto):
    assert interpretar(texto, planta).tipo == "confirma"


def test_una_correccion_que_termina_en_confirmo_no_es_una_confirmacion(planta):
    i = interpretar("No. La uno estaba en ciento quince kilos, no en ciento cincuenta. Corregilo y te confirmo.", planta)
    assert i.tipo == "corrige"
    assert i.correcciones == [{"tipo": "valor", "tag": "B-101", "unidad": "kg/cm2", "valor": 115.0, "mostrado": 150.0}]


def test_dos_correcciones_y_hay_mas(planta):
    i = interpretar("No. Eso de uno coma ocho era de el filtro B, no de el filtro A. Te faltó la dos, que estaba en "
                    "ciento veinte gotas por minuto. Y hay más cosas, revisalo todo.", planta)
    assert [c["tipo"] for c in i.correcciones] == ["equipo", "falta"]
    assert i.correcciones[0]["tag"] == "F-201B" and i.correcciones[0]["desde"] == "F-201A"
    assert i.correcciones[1] == {"tipo": "falta", "tag": "B-102", "unidad": "gotas/min", "valor": 120.0}
    assert i.hay_mas


def test_unidad_y_sobra(planta):
    i = interpretar("No. Lo de la dos es en psi, no en kilos. Lo de el pulmón no lo dije. Arreglá eso.", planta)
    assert [(c["tipo"], c["tag"]) for c in i.correcciones] == [("unidad", "B-102"), ("sobra", "TK-301")]


@pytest.mark.parametrize("texto, tag", [("Era la tres.", "B-103"), ("Ninguna de esas, era la dos.", "B-102")])
def test_elige_entre_opciones(planta, texto, tag):
    assert interpretar(texto, planta, candidatos=["B-101", "B-102", "B-103"]).elegido == tag


def test_no_entendio(planta):
    assert interpretar("No te entendí, ¿me lo repetís?", planta).tipo == "no_entendio"


def test_aplicar_correcciones(planta):
    filas = [FilaBorrador("B-101", "presion_descarga_local", 150, "kg/cm2"),
             FilaBorrador("F-201A", "presion_diferencial", 1.8, "kg/cm2"),
             FilaBorrador("TK-301", "nivel", 5.2, "m")]
    i = interpretar("No. La uno estaba en ciento quince kilos, no en ciento cincuenta. Eso de uno coma ocho era de el "
                    "filtro B, no de el filtro A. Corregilo y te confirmo.", planta)
    nuevas = aplicar(filas, i.correcciones, planta)
    assert [(f.tag, f.valor, f.unidad) for f in nuevas] == [("B-101", 115, "kg/cm2"), ("F-201B", 1.8, "kg/cm2"),
                                                           ("TK-301", 5.2, "m")]
    faltante = aplicar(nuevas, interpretar("No. Te faltó la dos, que estaba en ciento veinte gotas por minuto.",
                                           planta).correcciones, planta)
    assert (faltante[-1].tag, faltante[-1].variable, faltante[-1].valor) == ("B-102", "goteo_empaquetadura", 120)


def test_el_goteo_dictado_sin_numero_se_completa_sin_pisar_la_temperatura(planta):
    filas = [FilaBorrador("B-102", "goteo_empaquetadura", None, "gotas/min", "pérdida importante por empaquetadura"),
             FilaBorrador("B-102", "temperatura_rodamiento_ir", 56, "degC")]
    i = interpretar("No. La dos estaba en ciento cuarenta gotas por minuto, no en cincuenta y seis. Te faltó la dos, "
                    "que estaba en cincuenta y seis grados. Corregilo y te confirmo.", planta)
    nuevas = aplicar(filas, i.correcciones, planta)
    assert sorted((f.variable, f.valor, f.unidad) for f in nuevas) == [
        ("goteo_empaquetadura", 140, "gotas/min"), ("temperatura_rodamiento_ir", 56, "degC")]


def test_mensajes(planta):
    filas = [FilaBorrador("B-102", "presion_descarga_local", 1640, "psi"),
             FilaBorrador("F-201B", "presion_diferencial", 1.8, "kg/cm2", valor_dicho=18)]
    assert "la dos descarga 1640 psi" in texto_borrador(filas, planta)
    assert opciones_de_valor(filas) == ["Sí, 1,8", "No, 18"]
    ambigua = FilaBorrador(None, "presion_descarga_local", 112, None, dicho="la bomba",
                           candidatos=["B-101", "B-102", "B-103"])
    texto, opciones = pregunta_equipo(ambigua, planta)
    assert "qué bomba" in texto and opciones[1] == "La dos (B-102)"
