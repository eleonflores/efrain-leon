"""Diálogo con el operador por la tablet: borrador, preguntas y correcciones."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sistema.dominio.planta import Planta
from sistema.procesamiento.numeros import normalizar_numeros, sin_tildes
from sistema.procesamiento.parte import FilaBorrador

UNIDAD_DICHA = {"kilos": "kg/cm2", "kilo": "kg/cm2", "kilogramos": "kg/cm2", "psi": "psi", "libras": "psi",
                "bar": "bar", "bares": "bar", "metros": "m", "metro": "m", "grados": "degC",
                "gotas por minuto": "gotas/min", "gotas": "gotas/min"}
UNIDAD_VISIBLE = {"kg/cm2": "kg/cm²", "psi": "psi", "bar": "bar", "m": "m", "degC": "°C", "gotas/min": "gotas/min"}
NOMBRE_VARIABLE = {"presion_descarga_local": "descarga", "presion_diferencial": "diferencial", "nivel": "nivel",
                   "temperatura_rodamiento_ir": "rodamiento (IR)", "temperatura_motor_ir": "motor (IR)",
                   "goteo_empaquetadura": "empaquetadura", "nivel_aceite_visor": "aceite", "estado_correas": "correas",
                   "ruido": "ruido", "estado": "estado"}
_UNIDADES_RE = "|".join(sorted(map(re.escape, UNIDAD_DICHA), key=len, reverse=True))
_NUM = r"(\d+(?:\.\d+)?)"


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", sin_tildes(normalizar_numeros(texto).lower())).strip()


def _fmt(valor: float | None) -> str:
    if valor is None:
        return ""
    return (f"{valor:g}" if float(valor).is_integer() else f"{valor:g}").replace(".", ",")


def nombre_de(planta: Planta, tag: str | None) -> str:
    if tag is None:
        return "?"
    e = planta.equipos.get(tag)
    return e.nombres[0] if e and e.nombres else tag


def texto_borrador(filas: list[FilaBorrador], planta: Planta) -> str:
    partes = []
    for f in filas:
        if f.valor is not None:
            partes.append(f"{nombre_de(planta, f.tag)} {NOMBRE_VARIABLE.get(f.variable, f.variable)} "
                          f"{_fmt(f.valor)} {UNIDAD_VISIBLE.get(f.unidad or '', f.unidad or '')}".strip())
        elif f.observacion:
            partes.append(f"{nombre_de(planta, f.tag)}: {f.observacion}")
    texto = "Te leo el parte: " + "; ".join(partes) + "." if partes else "No encontré lecturas en la nota."
    for f in filas:
        if f.valor_dicho is not None:
            texto += (f" Entendí {_fmt(f.valor_dicho)} de diferencial en {nombre_de(planta, f.tag)}; lo anoto como "
                      f"{_fmt(f.valor)}.")
        if f.fuera_de_rango:
            texto += f" Ojo: {nombre_de(planta, f.tag)} {f.fuera_de_rango}."
    return texto + " ¿Lo confirmás?"


def opciones_de_valor(filas: list[FilaBorrador]) -> list[str]:
    f = next((f for f in filas if f.valor_dicho is not None), None)
    return [f"Sí, {_fmt(f.valor)}", f"No, {_fmt(f.valor_dicho)}"] if f else []


def pregunta_equipo(fila: FilaBorrador, planta: Planta) -> tuple[str, list[str]]:
    tipo = planta.equipos[fila.candidatos[0]].tipo if fila.candidatos else "equipo"
    que = {"bomba": "qué bomba", "filtro": "qué filtro"}.get(tipo, "qué equipo")
    dato = f" ({NOMBRE_VARIABLE.get(fila.variable, fila.variable)} {_fmt(fila.valor)})" if fila.valor is not None else ""
    texto = f"Dijiste \"{fila.dicho}\"{dato}: ¿de {que} hablás?"
    opciones = [f"{nombre_de(planta, t).capitalize()} ({t})" for t in fila.candidatos]
    return texto, opciones


@dataclass
class Interpretacion:
    tipo: str                                  # "confirma" | "corrige" | "elige" | "no_entendio" | "desconocida"
    correcciones: list[dict] = field(default_factory=list)
    hay_mas: bool = False
    elegido: str | None = None


CONFIRMA = re.compile(r"^(si\b|esta bien|correcto|perfecto|confirmo|dale|exacto|asi es)")
_PATRONES = [
    ("valor", re.compile(rf"(?P<nombre>[\w\s]+?) estaba en {_NUM}(?: (?P<unidad>{_UNIDADES_RE}))?,? no en {_NUM}")),
    ("equipo", re.compile(rf"eso de {_NUM}(?: (?P<unidad>{_UNIDADES_RE}))? era de (?P<nombre>[\w\s]+?),? no de "
                          rf"(?P<otro>[\w\s]+?)(?:[.,]|$)")),
    ("unidad", re.compile(rf"lo de (?P<nombre>[\w\s]+?) es en (?P<unidad>{_UNIDADES_RE}),? no en")),
    ("falta", re.compile(rf"te falto (?P<nombre>[\w\s]+?),? que estaba en {_NUM}(?: (?P<unidad>{_UNIDADES_RE}))?")),
    ("sobra", re.compile(r"lo de (?P<nombre>[\w\s]+?) no lo dije")),
]


def interpretar(texto: str, planta: Planta, candidatos: list[str] | None = None) -> Interpretacion:
    """Entiende la respuesta del operador a un borrador o a una pregunta de equipo."""
    t = _norm(texto)
    if candidatos:
        elegidos = [tag for tag in planta.equipos_en_texto(texto) if tag in candidatos]
        if not elegidos:
            elegidos = [tag for tag in candidatos if tag.lower() in t]
        if elegidos:
            return Interpretacion("elige", elegido=elegidos[-1])   # "Ninguna de esas, era la dos": la última
        return Interpretacion("no_entendio")
    if not t.startswith("no") and CONFIRMA.search(t):
        return Interpretacion("confirma")
    if t.startswith(("no te entendi", "como?", "repetime", "de que nota", "confirmar que")):
        return Interpretacion("no_entendio")
    correcciones = []
    for tipo, patron in _PATRONES:
        for m in patron.finditer(t):
            g = m.groupdict()
            nums = [float(x) for x in m.groups() if x and re.fullmatch(r"\d+(?:\.\d+)?", x)]
            tag = planta.resolver(g.get("nombre"))
            c = {"tipo": tipo, "tag": tag, "unidad": UNIDAD_DICHA.get(g.get("unidad") or "")}
            if tipo == "valor":
                c.update(valor=nums[0], mostrado=nums[-1])
            elif tipo == "equipo":
                c.update(valor=nums[0], desde=planta.resolver(g.get("otro")))
            elif tipo == "falta":
                c.update(valor=nums[0])
            if tag:
                correcciones.append(c)
    if correcciones:
        return Interpretacion("corrige", correcciones, hay_mas="hay mas cosas" in t)
    return Interpretacion("desconocida")


def _variable_por_unidad(unidad: str | None, tag: str, planta: Planta) -> str:
    tipo = planta.equipos[tag].tipo if tag in planta.equipos else "bomba"
    if unidad == "gotas/min":
        return "goteo_empaquetadura"
    if unidad == "m" or tipo == "tanque":
        return "nivel"
    if unidad == "degC":
        return "temperatura_rodamiento_ir"
    return "presion_diferencial" if tipo == "filtro" else "presion_descarga_local"


def _cerca(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= max(0.051, abs(b) * 0.015)


def aplicar(filas: list[FilaBorrador], correcciones: list[dict], planta: Planta) -> list[FilaBorrador]:
    filas = list(filas)
    for c in correcciones:
        tag = c["tag"]
        con_valor = [f for f in filas if f.valor is not None]
        if c["tipo"] == "valor":
            # "la dos estaba en 140 gotas por minuto, no en 56": la fila sale de la unidad dicha
            f = _fila_de_la_unidad(filas, tag, c["unidad"], planta)
            if f is None and not _unidad_choca(c["unidad"], tag, planta, con_valor, c["mostrado"]):
                f = next((f for f in con_valor if f.tag == tag and _cerca(f.valor, c["mostrado"])), None) \
                    or next((f for f in con_valor if f.tag == tag), None)
            if f:
                f.valor, f.valor_dicho, f.fuera_de_rango = c["valor"], None, None
                f.unidad = c["unidad"] or f.unidad
            else:
                filas.append(_nueva(tag, c, planta))
        elif c["tipo"] == "equipo":
            f = next((f for f in con_valor if _cerca(f.valor, c["valor"]) and (c.get("desde") in (None, f.tag))), None)
            if f:
                f.tag, f.candidatos, f.fuera_de_rango = tag, [], None
                if f.variable == "presion_descarga_local" and c["unidad"] is None:
                    f.unidad = planta.unidad_por_defecto(tag, f.variable)
        elif c["tipo"] == "unidad":
            f = next((f for f in con_valor if f.tag == tag), None)
            if f:
                f.unidad, f.fuera_de_rango = c["unidad"], None
        elif c["tipo"] == "falta":
            f = _fila_de_la_unidad(filas, tag, c["unidad"], planta)
            if f is not None and f.valor is None:
                f.valor, f.unidad = c["valor"], c["unidad"] or f.unidad    # el goteo dictado sin número
            elif f is None or not _cerca(f.valor, c["valor"]):           # si ya está, no se duplica
                filas.append(_nueva(tag, c, planta))
        elif c["tipo"] == "sobra":
            sobrante = next((f for f in reversed(con_valor) if f.tag == tag), None)
            if sobrante:
                filas.remove(sobrante)
    return filas


def _fila_de_la_unidad(filas: list[FilaBorrador], tag: str, unidad: str | None, planta: Planta) -> FilaBorrador | None:
    """La fila del equipo cuya variable se mide en esa unidad (p. ej. gotas/min → el goteo de la empaquetadura)."""
    if unidad is None:
        return None
    variable = _variable_por_unidad(unidad, tag, planta)
    return next((f for f in filas if f.tag == tag and f.variable == variable), None)


def _unidad_choca(unidad: str | None, tag: str, planta: Planta, con_valor: list[FilaBorrador], mostrado: float) -> bool:
    """True si la unidad corregida no puede ser la de la fila que mostraba ese valor (gotas/min sobre una temperatura)."""
    if unidad is None:
        return False
    fila = next((f for f in con_valor if f.tag == tag and _cerca(f.valor, mostrado)), None)
    return fila is not None and _variable_por_unidad(unidad, tag, planta) != fila.variable and not (
        unidad in ("kg/cm2", "psi", "bar") and fila.variable in ("presion_descarga_local", "presion_diferencial"))


def _nueva(tag: str, c: dict, planta: Planta) -> FilaBorrador:
    variable = _variable_por_unidad(c.get("unidad"), tag, planta)
    unidad = c.get("unidad") or planta.unidad_por_defecto(tag, variable)
    return FilaBorrador(tag, variable, c["valor"], unidad, dicho="corrección del operador")
