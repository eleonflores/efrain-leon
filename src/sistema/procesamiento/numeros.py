"""Números hablados en español de campo → números.

El operador dicta "mil seiscientos cuarenta psi", "uno ocho de diferencial", "cinco coma dos metros",
"uno y medio" o "cincuenta y dos grados". La transcripción puede devolverlos en palabras o en dígitos
("1.640", "1,8"). Este módulo los lleva a una forma única con punto decimal ("1640", "1.8") sin tocar el
resto del texto, para que la extracción del parte trabaje sobre números y no sobre palabras.

Cuidados:
- "la uno", "la dos", "bomba tres" son nombres de equipos, no lecturas: se dejan en palabras.
- "un"/"una" casi siempre son artículos ("un golpeteo"): solo cuentan como 1 dentro de un número compuesto
  ("cincuenta y un grados", "veintiún") o delante de una unidad ("un kilo").
- Dos dígitos sueltos seguidos ("uno ocho") son un decimal: así dicta el operador los diferenciales.
"""

from __future__ import annotations

import re
import unicodedata

UNIDADES = {
    "cero": 0, "uno": 1, "un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21,
    "veintiun": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
DECENAS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80,
           "noventa": 90}
CENTENAS = {"cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300, "cuatrocientos": 400,
            "quinientos": 500, "seiscientos": 600, "setecientos": 700, "ochocientos": 800, "novecientos": 900}
SEPARADOR_DECIMAL = {"coma", "con", "punto"}
UNIDADES_FISICAS = {"grado", "grados", "kilo", "kilos", "kilogramo", "kilogramos", "metro", "metros", "bar",
                    "bares", "psi", "libra", "libras", "gota", "gotas"}
# "la dos", "bomba tres": se quedan en palabras. "a uno" y "las dos" son "la uno" y "la dos" mal transcriptos.
NOMBRE_DE_EQUIPO = {"la", "bomba", "las", "a"}
_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+|\s+|.", re.UNICODE)


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _clave(palabra: str) -> str:
    return sin_tildes(palabra.lower())


def _es_palabra_numero(clave: str) -> bool:
    return clave in UNIDADES or clave in DECENAS or clave in CENTENAS or clave == "mil"


def _digitos(token: str) -> float:
    """'1.640' → 1640 (separador de miles); '1,8' y '1.8' → 1.8."""
    if "," in token:
        return float(token.replace(".", "").replace(",", "."))
    partes = token.split(".")
    if len(partes) > 1 and all(len(p) == 3 for p in partes[1:]):
        return float("".join(partes))
    return float(token)


def _formatear(valor: float) -> str:
    return str(int(valor)) if float(valor).is_integer() else f"{valor:.10g}"


class _Lector:
    def __init__(self, texto: str):
        self.tokens = _TOKEN.findall(texto)
        self.i = 0

    def _siguiente_palabra(self, desde: int) -> int | None:
        j = desde
        while j < len(self.tokens) and self.tokens[j].isspace():
            j += 1
        return j if j < len(self.tokens) else None

    def _entero(self, desde: int) -> tuple[int, int, int] | None:
        """Lee un entero en palabras desde `desde`. Devuelve (valor, índice siguiente, cantidad de palabras)."""
        total, actual, palabras, j, ultimo = 0, 0, 0, desde, None
        while True:
            k = self._siguiente_palabra(j) if palabras else j
            if k is None:
                break
            c = _clave(self.tokens[k])
            if c == "y" and ultimo in DECENAS:
                k2 = self._siguiente_palabra(k + 1)
                if k2 is not None and _clave(self.tokens[k2]) in UNIDADES and UNIDADES[_clave(self.tokens[k2])] < 10:
                    actual += UNIDADES[_clave(self.tokens[k2])]
                    j, ultimo, palabras = k2 + 1, "unidad", palabras + 2
                    continue
                break
            if c in CENTENAS and (ultimo is None or ultimo == "mil"):
                actual += CENTENAS[c]
            elif c in DECENAS and (ultimo in (None, "mil") or ultimo in CENTENAS):
                actual += DECENAS[c]
            elif c in UNIDADES and (ultimo in (None, "mil") or ultimo in CENTENAS):
                actual += UNIDADES[c]
            elif c == "mil" and ultimo != "mil":
                total += (actual or 1) * 1000
                actual = 0
            else:
                break
            ultimo = c if c in CENTENAS or c in DECENAS or c == "mil" else "unidad"
            palabras += 1
            j = k + 1
        if palabras == 0:
            return None
        return total + actual, j, palabras

    def leer(self) -> str:
        salida: list[str] = []
        while self.i < len(self.tokens):
            tok = self.tokens[self.i]
            c = _clave(tok)
            if tok[0].isdigit():
                if re.fullmatch(r"0\d", tok):          # "09": lo resuelve el contexto (diferencial "cero nueve")
                    salida.append(tok)
                    self.i += 1
                    continue
                if tok in ("1", "2", "3") and self._palabra_anterior() in NOMBRE_DE_EQUIPO:
                    salida.append({"1": "uno", "2": "dos", "3": "tres"}[tok])     # "la 2" es "la dos"
                    self.i += 1
                    continue
                valor, fin = _digitos(tok), self.i + 1
                valor, fin = self._decimal(valor, fin, palabras=0, era_digito=True)
                salida.append(_formatear(valor))
                self.i = fin
                continue
            if not _es_palabra_numero(c) or not self._cuenta_como_numero(c):
                salida.append(tok)
                self.i += 1
                continue
            leido = self._entero(self.i)
            if leido is None:
                salida.append(tok)
                self.i += 1
                continue
            valor, fin, palabras = leido
            valor, fin = self._mezcla_con_digitos(valor, fin)
            valor, fin = self._decimal(float(valor), fin, palabras, era_digito=False)
            salida.append(_formatear(valor))
            self.i = fin
        return "".join(salida)

    def _mezcla_con_digitos(self, valor: int, fin: int) -> tuple[int, int]:
        """La transcripción a veces mezcla: "mil seiscientos 20" es 1620, no 1600 y 20."""
        k = self._siguiente_palabra(fin)
        if k is None or not self.tokens[k].isdigit():
            return valor, fin
        resto = int(self.tokens[k])
        if (valor >= 1000 and valor % 1000 == 0 and resto < 1000) or (valor >= 100 and valor % 100 == 0 and resto < 100):
            return valor + resto, k + 1
        return valor, fin

    def _cuenta_como_numero(self, c: str) -> bool:
        anterior = self._palabra_anterior()
        if anterior in NOMBRE_DE_EQUIPO and c in ("uno", "dos", "tres", "1", "2", "3"):
            return False
        if c in ("un", "una"):
            k = self._siguiente_palabra(self.i + 1)
            return k is not None and _clave(self.tokens[k]) in UNIDADES_FISICAS
        return True

    def _palabra_anterior(self) -> str | None:
        j = self.i - 1
        while j >= 0 and self.tokens[j].isspace():
            j -= 1
        return _clave(self.tokens[j]) if j >= 0 else None

    def _decimal(self, valor: float, fin: int, palabras: int, era_digito: bool) -> tuple[float, int]:
        """Completa la parte decimal: "uno coma ocho", "uno con ocho", "uno y medio", "uno ocho"."""
        if not float(valor).is_integer():
            return valor, fin
        k = self._siguiente_palabra(fin)
        if k is None:
            return valor, fin
        c = _clave(self.tokens[k])
        if c in SEPARADOR_DECIMAL:
            k2 = self._siguiente_palabra(k + 1)
            if k2 is not None:
                if self.tokens[k2][0].isdigit():
                    return float(f"{int(valor)}.{self.tokens[k2]}"), k2 + 1
                leido = self._entero(k2)
                if leido and leido[0] < 100:
                    return float(f"{int(valor)}.{leido[0]}"), leido[1]
            return valor, fin
        if c == "y":
            k2 = self._siguiente_palabra(k + 1)
            if k2 is not None and _clave(self.tokens[k2]) == "medio":
                return valor + 0.5, k2 + 1
            return valor, fin
        # "uno ocho": dos dígitos sueltos en palabras, el segundo solo.
        if not era_digito and palabras == 1 and valor < 10 and c in UNIDADES and UNIDADES[c] < 10 and c not in ("un", "una"):
            leido = self._entero(k)
            if leido and leido[2] == 1:
                return float(f"{int(valor)}.{UNIDADES[c]}"), leido[1]
        return valor, fin


# El diferencial de un filtro siempre es un decimal chico ("uno ocho" = 1.8). La transcripción suele partirlo en dos
# números: "uno, dos", "1 o 2", "1-3", "unos 5", "09". Delante de "de diferencial" se vuelven a juntar.
_DIFERENCIAL = r"(?=\s+de\s+diferencial)"
_ARREGLOS_DIFERENCIAL = [
    (re.compile(r"\b(\d)\s*(?:,|-|\bo\b)\s*(\d)\b" + _DIFERENCIAL), r"\1.\2"),
    (re.compile(r"\b(\d) (\d)\b" + _DIFERENCIAL), r"\1.\2"),
    (re.compile(r"\bunos\s+(\d)\b" + _DIFERENCIAL, re.IGNORECASE), r"1.\1"),
    (re.compile(r"\b0(\d)\b" + _DIFERENCIAL), r"0.\1"),
]


def _arreglar_diferenciales(texto: str) -> str:
    for patron, reemplazo in _ARREGLOS_DIFERENCIAL:
        texto = patron.sub(reemplazo, texto)
    return texto


def normalizar_numeros(texto: str) -> str:
    """Reemplaza los números hablados o escritos por dígitos con punto decimal; el resto queda igual."""
    return _arreglar_diferenciales(_Lector(texto).leer())


def extraer_numeros(texto: str) -> list[float]:
    """Los números del texto, en orden, después de normalizarlos."""
    return [_digitos(n) for n in re.findall(r"\d+(?:\.\d+)?", normalizar_numeros(texto))]
