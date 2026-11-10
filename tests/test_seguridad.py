import pytest

from sistema.procesamiento.seguridad import detectar

# Textos exactos de las notas de seguridad del operador virtual (planta_sim/operador.py, nota_seguridad).
INSEGURAS = [
    ("S1", "¡Atención! Se rompió algo en la descarga de la uno, sale agua a presión para todos lados, me alejé. "
           "Saqué foto desde lejos."),
    ("S2", "Hay olor a gas fuerte del lado del portón, viene del lado del separador."),
    ("S3", "Sale humo del motor de la dos, hay olor a quemado."),
    ("S4", "Mi compañero se golpeó la mano con la llave en el skid de filtros, está sangrando bastante."),
    # Variantes que puede devolver la transcripción
    ("S1", "atención se rompió algo en la descarga de la de la punta sale agua a presión para todos lados"),
    ("S4", "mi compañero se golpeo la mano con la llave esta sangrando bastante"),
]

# Frases normales del operador que no son condiciones inseguras.
NORMALES = [
    "La dos hace un golpeteo metálico.",
    "La uno chorrea por la empaquetadura, le saqué foto.",
    "La tres pierde bastante por la empaquetadura, le saqué foto.",
    "En la dos, el rodamiento me dio setenta y ocho grados con la pistola, tiene un ruido raro de rodamiento.",
    "El pulmón está en cinco coma dos metros, está rebalsando a la pileta.",
    "La uno suena como si tuviera piedras adentro.",
    "Las correas están flojas, chillan, saqué foto.",
    "La tres está disparada, no arranca.",
    "El filtro B me dio uno ocho de diferencial, le saqué foto al manómetro.",
    "Recorrida sin novedad, todo normal.",
]


@pytest.mark.parametrize("codigo, texto", INSEGURAS)
def test_detecta_condiciones_inseguras(codigo, texto):
    assert codigo in {c.codigo for c in detectar(texto)}


@pytest.mark.parametrize("texto", NORMALES)
def test_no_da_falsas_alarmas(texto):
    assert detectar(texto) == []
