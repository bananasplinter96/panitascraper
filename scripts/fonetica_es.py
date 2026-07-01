"""
Similitud fonética para nombres en español (sin dependencias externas).

Basado en el mismo principio usado en proyectos de matching de nombres
post-desastre (ej. IOM/PDNA Haití): reducir el nombre a un código que
agrupa letras/sonidos equivalentes, para detectar variantes de
transcripción (acentos, "b"/"v", "s"/"z"/"c", "y"/"ll", apellidos en
distinto orden) que un match exacto de texto no captura.
"""

import difflib
import re
import unicodedata

_EQUIV = [
    (r"[áàäâ]", "a"), (r"[éèëê]", "e"), (r"[íìïî]", "i"),
    (r"[óòöô]", "o"), (r"[úùüû]", "u"),
    (r"ñ", "n"),
    (r"[bv]", "b"),
    (r"ll", "y"),
    (r"[sz]", "s"),
    (r"c([ei])", r"s\1"),
    (r"qu", "k"),
    (r"c", "k"),
    (r"h", ""),
    (r"g([ei])", r"j\1"),
    (r"y$", "i"),
    (r"(.)\1+", r"\1"),  # colapsa letras repetidas
]


def normalizar(nombre: str) -> str:
    """Mayúsculas, sin acentos/puntuación, espacios colapsados."""
    n = unicodedata.normalize("NFKD", nombre or "")
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = re.sub(r"[^a-zA-Z\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip().upper()
    return n


def codigo_fonetico(token: str) -> str:
    """Reduce un token a un código fonético aproximado."""
    t = token.lower()
    for pat, repl in _EQUIV:
        t = re.sub(pat, repl, t)
    return t


def tokens_foneticos(nombre: str) -> set[str]:
    return {codigo_fonetico(tok) for tok in normalizar(nombre).split() if tok}


def comparar(nombre_a: str, nombre_b: str) -> tuple[str, float]:
    """
    Compara dos nombres y devuelve (categoria, score).
    categoria: 'exacta' | 'exacta_reordenada' | 'fonetica' | 'no_coincide'
    """
    na, nb = normalizar(nombre_a), normalizar(nombre_b)
    if not na or not nb:
        return "no_coincide", 0.0

    if na == nb:
        return "exacta", 1.0

    tokens_a, tokens_b = set(na.split()), set(nb.split())
    if tokens_a == tokens_b:
        return "exacta_reordenada", 0.98

    # Contención en vez de unión: los registros oficiales suelen traer el
    # nombre legal completo (con apellido materno, segundo nombre) mientras
    # que el reporte ciudadano trae solo nombre + apellido. Penalizar por
    # esa diferencia de longitud generaría muchos falsos "no_coincide".
    fon_a, fon_b = tokens_foneticos(nombre_a), tokens_foneticos(nombre_b)
    overlap = len(fon_a & fon_b)
    menor = min(len(fon_a), len(fon_b)) or 1
    fon_score = overlap / menor

    ratio = difflib.SequenceMatcher(None, na, nb).ratio()
    score = max(fon_score, ratio)

    if score >= 0.82:
        return "fonetica", round(score, 3)
    return "no_coincide", round(score, 3)
