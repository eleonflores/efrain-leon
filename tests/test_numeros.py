import pytest

from sistema.procesamiento.numeros import extraer_numeros, normalizar_numeros


@pytest.mark.parametrize(
    "texto, esperado",
    [
        # Frases reales del operador virtual (planta/sim/planta_sim/operador.py)
        ("La dos está en mil seiscientos cuarenta psi de descarga", "La dos está en 1640 psi de descarga"),
        ("el filtro B me dio uno ocho de diferencial", "el filtro B me dio 1.8 de diferencial"),
        ("el filtro A me dio uno coma cinco de diferencial", "el filtro A me dio 1.5 de diferencial"),
        ("el filtro A me dio uno con cinco de diferencial", "el filtro A me dio 1.5 de diferencial"),
        ("el filtro A me dio uno y medio de diferencial", "el filtro A me dio 1.5 de diferencial"),
        ("el pulmón está en cinco coma dos metros", "el pulmón está en 5.2 metros"),
        ("la uno está en ciento doce kilos de descarga", "la uno está en 112 kilos de descarga"),
        ("el rodamiento me dio cincuenta y dos grados con la pistola", "el rodamiento me dio 52 grados con la pistola"),
        ("el rodamiento me dio cincuenta y un grados", "el rodamiento me dio 51 grados"),
        ("el rodamiento me dio veintiún grados", "el rodamiento me dio 21 grados"),
        ("la tres está en ciento diez bar", "la tres está en 110 bar"),
        ("el filtro B me dio dieciocho de diferencial", "el filtro B me dio 18 de diferencial"),
        ("el pulmón está en seis metros", "el pulmón está en 6 metros"),
        ("la dos está en dos mil cien psi", "la dos está en 2100 psi"),
        # Lo que no es un número
        ("la tres está parada, en reserva", "la tres está parada, en reserva"),
        ("hace un golpeteo metálico", "hace un golpeteo metálico"),
        ("bomba dos", "bomba dos"),
        ("No, la uno estaba en ciento quince kilos", "No, la uno estaba en 115 kilos"),
        # Lo que devuelve la transcripción en dígitos
        ("La 2 está en 1.640 psi", "La dos está en 1640 psi"),
        ("bomba 3 parada", "bomba tres parada"),
        ("me dio 1,8 de diferencial", "me dio 1.8 de diferencial"),
        ("me dio 1.8 de diferencial", "me dio 1.8 de diferencial"),
        ("está en 112 de descarga", "está en 112 de descarga"),
    ],
)
def test_normalizar_numeros(texto, esperado):
    assert normalizar_numeros(texto) == esperado


@pytest.mark.parametrize(
    "transcripcion, esperado",
    [
        # Salidas reales de Whisper small sobre "uno dos de diferencial" y parecidas (evaluacion/stt)
        ("El de la izquierda me dio 1 o 2 de diferencial.", [1.2]),
        ("El de la izquierda me dio uno, dos de diferencial.", [1.2]),
        ("El filtro A me dio unos 5 de diferencial", [1.5]),
        ("El filtro A medió uno, dos de diferencial.", [1.2]),
        ("el filtro A medio 1-3 de diferencial", [1.3]),
        ("El de la derecha me dio 09 de diferencial.", [0.9]),
        # Lo que no hay que juntar
        ("El filtro B me dio 18 de diferencial.", [18]),
        ("La dos está en 1640 psi de descarga, el filtro B me dio 1.8 de diferencial.", [1640, 1.8]),
    ],
)
def test_diferenciales_partidos_por_la_transcripcion(transcripcion, esperado):
    assert extraer_numeros(transcripcion) == esperado


def test_extraer_numeros_de_una_nota_mezclada():
    nota = ("La dos está en ciento doce de descarga, ah, y el filtro B me dio uno ocho de diferencial. "
            "La tres sigue goteando por la empaquetadura, le saqué foto.")
    assert extraer_numeros(nota) == [112, 1.8]
