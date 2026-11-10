import pytest


@pytest.mark.parametrize("dicho, tag", [("la dos", "B-102"), ("la del portón", "B-101"), ("el filtro B", "F-201B"),
                                        ("B-102", "B-102")])
def test_resuelve_nombres_informales(planta, dicho, tag):
    assert planta.resolver(dicho) == tag


@pytest.mark.parametrize("dicho", ["la bomba", None])
def test_nombre_ambiguo_no_se_resuelve(planta, dicho):
    assert planta.resolver(dicho) is None


def test_equipos_en_texto_en_orden(planta):
    texto = "La dos está en 112 de descarga, ah, y el filtro B me dio 1.8 de diferencial. La tres sigue goteando."
    assert planta.equipos_en_texto(texto) == ["B-102", "F-201B", "B-103"]


def test_limites_de_la_hoja_de_datos(planta):
    assert planta.fuera_de_alarma("B-102", "presion_descarga_local", 1640, "psi") is None      # 115 kg/cm²
    assert planta.fuera_de_alarma("B-102", "presion_descarga_local", 1800, "psi")             # 126,6 kg/cm²
    assert planta.fuera_de_alarma("F-201B", "presion_diferencial", 1.5, "kg/cm2")             # alarma alta 1,5
    assert planta.fuera_de_alarma("F-201B", "presion_diferencial", 1.2, "kg/cm2") is None
