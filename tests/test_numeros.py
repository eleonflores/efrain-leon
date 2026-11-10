import pytest

from sistema.procesamiento.numeros import extraer_numeros, normalizar_numeros


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("La dos está en mil seiscientos cuarenta psi de descarga", "La dos está en 1640 psi de descarga"),
        ("el filtro B me dio uno ocho de diferencial", "el filtro B me dio 1.8 de diferencial"),
        ("el filtro A me dio uno coma cinco de diferencial", "el filtro A me dio 1.5 de diferencial"),
        ("el filtro A me dio uno y medio de diferencial", "el filtro A me dio 1.5 de diferencial"),
        ("la uno está en ciento doce kilos de descarga", "la uno está en 112 kilos de descarga"),
        ("el rodamiento me dio cincuenta y dos grados con la pistola", "el rodamiento me dio 52 grados con la pistola"),
        ("el rodamiento me dio cincuenta y un grados", "el rodamiento me dio 51 grados"),
        ("el rodamiento me dio veintiún grados", "el rodamiento me dio 21 grados"),
        ("el filtro B me dio dieciocho de diferencial", "el filtro B me dio 18 de diferencial"),
        ("la dos está en dos mil cien psi", "la dos está en 2100 psi"),
        ("hace un golpeteo metálico", "hace un golpeteo metálico"),
        ("bomba dos", "bomba dos"),
        ("La 2 está en 1.640 psi", "La dos está en 1640 psi"),
        ("A uno estar en ciento doce kilogramos de descarga", "A uno estar en 112 kilogramos de descarga"),
        ("Las dos está en 1640 libras", "Las dos está en 1640 libras"),
        ("me dio 1,8 de diferencial", "me dio 1.8 de diferencial"),
        ("me dio 1.8 de diferencial", "me dio 1.8 de diferencial"),
    ],
)
def test_normalizar_numeros(texto, esperado):
    assert normalizar_numeros(texto) == esperado


@pytest.mark.parametrize(
    "transcripcion, esperado",
    [
        ("El de la izquierda me dio 1 o 2 de diferencial.", [1.2]),
        ("El de la izquierda me dio uno, dos de diferencial.", [1.2]),
        ("El filtro A me dio unos 5 de diferencial", [1.5]),
        ("el filtro A medio 1-3 de diferencial", [1.3]),
        ("El de la derecha me dio 09 de diferencial.", [0.9]),
        ("El filtro B me dio 18 de diferencial.", [18]),
        ("La dos está en 1640 psi de descarga, el filtro B me dio 1.8 de diferencial.", [1640, 1.8]),
    ],
)
def test_diferenciales_partidos_por_la_transcripcion(transcripcion, esperado):
    assert extraer_numeros(transcripcion) == esperado
