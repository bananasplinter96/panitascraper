"""
Clasifica y repara registros de `personas` cuyo nombre contiene "/" —
un síntoma que en realidad mezcla 3 patrones distintos, originados
sobre todo en el spider `encuentralos` (que agrega/reconcilia datos de
varias fuentes citizen-report y a veces deja el proceso interno
expuesto en el campo nombre):

  1. variantes_ocr: varias lecturas/grafías del MISMO nombre separadas
     por "/" (ej. "RODRIGO OLIVA JOELVINYER JESUS / RODRIGO OLIVIA ...").
     SE ARREGLA AUTOMÁTICAMENTE: se toma la primera variante como
     nombre canónico y se guardan las demás en notas para no perder
     el dato.

  2. notas_administrativas: no es un nombre en absoluto — es un
     comentario de reconciliación de cédulas de alguna herramienta
     externa (contiene "C.I. registrada como", "ecrespo-github",
     "coincidencia"). NO se repara automáticamente — requiere que
     alguien decida cuál cédula es la correcta.

  3. mensaje_multiple: un mensaje de WhatsApp con varias personas
     mencionadas, pegado como si fuera un solo nombre (empieza con
     "[DD/M, HH:MM"). NO se repara automáticamente — habría que
     separar en varias personas y no hay forma confiable de hacerlo
     sin revisión humana.

  4. canonico_sospechoso: dentro de variantes_ocr, casos donde "tomar
     la primera parte" da un resultado sin letras suficientes para ser
     un nombre (ej. "R / N Parra" -> canónico "R", perdiendo el
     apellido real; probablemente "R/N" = abreviatura médica de
     "Recién Nacido" partida por el separador), donde la primera parte
     trae una marca explícita de incertidumbre como "[Ilegible]" (ej.
     "Alexey [Ilegible] / Jose Cleonir Marley" -> canónico "Alexey
     [Ilegible]", descartando el nombre legible), o donde el canónico
     es mucho más corto que la variante descartada (señal de que un
     nombre completo se partió por accidente en apellido/nombre, ej.
     "RAMOS/SILVA MARYELIS" -> canónico "RAMOS", perdiendo "Silva
     Maryelis"). NO se repara automáticamente — requiere decidir a
     mano cuál parte es el nombre real.

  5. posible_inyeccion: el nombre contiene sintaxis de marcado HTML o
     un vector de inyección conocido (ej. '"><svg/onload=(...)>',
     capturado tal cual de un intento de XSS contra el sitio fuente).
     NO es un nombre real, no se repara — solo se reporta para que un
     humano decida borrar la fila.

Por defecto solo reporta. Usa --apply para aplicar la reparación
automática del grupo 'variantes_ocr' únicamente. Los demás grupos
nunca se tocan por este script, sin importar --apply.

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5432/panitasmap \
    python scripts/fix_name_variants.py [--apply]
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import get_engine

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: define DATABASE_URL (ver .env.example)")

_ADMIN_RE = re.compile(r"C\.I\.\s*registrada|ecrespo-github|coincidencia\s*~?\d+%", re.IGNORECASE)
_WHATSAPP_RE = re.compile(r"^\s*\[\d{1,2}/\d{1,2},\s*\d{1,2}:\d{2}")
_MARKUP_RE = re.compile(r"<[a-zA-Z!/][^>]*>|javascript:|on(error|load)\s*=", re.IGNORECASE)


def clasificar(nombre: str) -> str:
    if _MARKUP_RE.search(nombre):
        return "posible_inyeccion"
    if _ADMIN_RE.search(nombre):
        return "notas_administrativas"
    if _WHATSAPP_RE.match(nombre):
        return "mensaje_multiple"
    return "variantes_ocr"


def dividir_variantes(nombre: str) -> tuple[str, list[str]]:
    partes = [p.strip() for p in re.split(r"\s*/\s*", nombre) if p.strip()]
    if not partes:
        return nombre.strip(), []
    return partes[0], partes[1:]


_LETRAS_RE = re.compile(r"[^A-Za-zÀ-ÿ]")


_ILEGIBLE_RE = re.compile(r"ilegible", re.IGNORECASE)


def canonico_sospechoso(canonico: str, variantes: list[str] | None = None) -> bool:
    """True si el candidato a nombre canónico tiene muy pocas letras
    para ser un nombre real (ej. 'R', 'P.2') — señal de que la parte
    antes del '/' era una abreviatura/anotación, no un nombre —, si
    contiene una marca explícita de incertidumbre como '[Ilegible]',
    o si es mucho más corto que la variante descartada más larga
    (señal de que un nombre completo se partió por accidente)."""
    if _ILEGIBLE_RE.search(canonico):
        return True
    if len(_LETRAS_RE.sub("", canonico)) <= 2:
        return True
    if variantes:
        largo_max = max(len(v) for v in variantes)
        if largo_max > 0 and len(canonico) < largo_max * 0.4:
            return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Aplicar la reparación automática del grupo 'variantes_ocr'")
    args = parser.parse_args()

    engine = get_engine(DATABASE_URL)
    with Session(engine) as session:
        rows = session.execute(text(
            "SELECT id, nombre, notas FROM personas WHERE nombre LIKE '%/%'"
        )).fetchall()

        grupos: dict[str, list] = {
            "variantes_ocr": [],
            "notas_administrativas": [],
            "mensaje_multiple": [],
            "canonico_sospechoso": [],
            "posible_inyeccion": [],
        }
        for persona_id, nombre, notas in rows:
            grupo = clasificar(nombre)
            if grupo == "variantes_ocr":
                canonico, variantes = dividir_variantes(nombre)
                if canonico_sospechoso(canonico, variantes):
                    grupo = "canonico_sospechoso"
            grupos[grupo].append((persona_id, nombre, notas))

        print(f"Total con '/' en el nombre: {len(rows)}")
        for grupo, items in grupos.items():
            print(f"  {grupo}: {len(items)}")

        print("\n--- Muestra: notas_administrativas (revisión manual, NO se toca) ---")
        for persona_id, nombre, _ in grupos["notas_administrativas"][:10]:
            print(f"  id={persona_id}\n    nombre='{nombre[:150]}...'")

        print("\n--- Muestra: mensaje_multiple (revisión manual, NO se toca) ---")
        for persona_id, nombre, _ in grupos["mensaje_multiple"][:10]:
            print(f"  id={persona_id}\n    nombre='{nombre[:150]}...'")

        print("\n--- Muestra: canonico_sospechoso (revisión manual, NO se toca) ---")
        for persona_id, nombre, _ in grupos["canonico_sospechoso"][:10]:
            canonico, variantes = dividir_variantes(nombre)
            print(f"  id={persona_id}\n    nombre='{nombre}'\n    canónico descartado por sospechoso='{canonico}'")

        print("\n--- posible_inyeccion (revisión manual — candidatas a BORRAR, no son nombres) ---")
        for persona_id, nombre, _ in grupos["posible_inyeccion"]:
            print(f"  id={persona_id}\n    nombre='{nombre}'")

        print("\n--- Muestra: variantes_ocr (se repara automáticamente con --apply) ---")
        for persona_id, nombre, _ in grupos["variantes_ocr"][:10]:
            canonico, variantes = dividir_variantes(nombre)
            print(f"  id={persona_id}\n    nombre nuevo='{canonico}'\n    variantes guardadas='{' | '.join(variantes)}'")

        if args.apply:
            print("\nAplicando reparación a 'variantes_ocr'...")
            aplicadas = 0
            for persona_id, nombre, notas in grupos["variantes_ocr"]:
                canonico, variantes = dividir_variantes(nombre)
                if not variantes:
                    continue
                nota_variantes = f"[Variantes de nombre detectadas: {' | '.join(variantes)}]"
                nuevas_notas = f"{nota_variantes} {(notas or '')}".strip()
                session.execute(
                    text("UPDATE personas SET nombre = :n, notas = :notas, updated_at = NOW() WHERE id = :id"),
                    {"n": canonico, "notas": nuevas_notas, "id": persona_id},
                )
                aplicadas += 1
            session.commit()
            print(f"Reparadas {aplicadas} filas de 'variantes_ocr'.")
            print(f"'notas_administrativas' ({len(grupos['notas_administrativas'])}), "
                  f"'mensaje_multiple' ({len(grupos['mensaje_multiple'])}), "
                  f"'canonico_sospechoso' ({len(grupos['canonico_sospechoso'])}) y "
                  f"'posible_inyeccion' ({len(grupos['posible_inyeccion'])}) "
                  f"NO se tocaron — requieren revisión manual.")
        else:
            print("\n(Modo reporte — no se modificó nada. Usa --apply para reparar 'variantes_ocr'.)")


if __name__ == "__main__":
    main()
