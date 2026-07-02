"""
Clasifica los ~99k candidatos a duplicado fonético (ver sección 4 de
data_quality_report.py) por nivel de confianza, y estima cuántas
personas ÚNICAS reales hay detrás de las 206,926 filas de `personas`
si se fusionaran los duplicados con evidencia fuerte.

Un candidato fonético por sí solo NO basta para fusionar automáticamente
dos fichas: el nombre es el campo con más ruido de transcripción de toda
la tabla, así que "se parece el nombre" produce muchos falsos positivos
entre personas DISTINTAS con nombres comunes. Este reporte agrega
cédula como señal adicional para separar:

  ALTA:  ambas fichas tienen cédula (normalizada a solo dígitos, 6-9
         dígitos) y coinciden exactamente. Evidencia fuerte de que es
         la misma persona reportada más de una vez.
  MEDIA: score fonético == 1.0 (la comparación más alta que da
         fonetica_es.comparar) Y edad idéntica (no solo compatible
         dentro de un rango) cuando ambas están presentes.
  BAJA:  todo lo demás que ya pasó el filtro de score+edad+hospital de
         reporte_duplicados_foneticos() pero sin la evidencia anterior.

Con eso se construye un grafo de "misma persona" usando SOLO aristas
ALTA (unión-find) y se cuenta cuántos componentes conectados resultan
— esa es la estimación conservadora de personas únicas tras fusionar
los duplicados más seguros. Es una cota superior real: fusionar más
(incluyendo MEDIA) bajaría aún más el número, pero con más riesgo de
falso positivo.

No modifica nada — solo reporta, para decidir con datos si conviene
construir un fix_duplicados.py semi-automático (solo para el tier ALTA).

Uso:
    DATABASE_URL=postgresql://<user>:<pass>@localhost:5432/panitasmap \
    python scripts/duplicate_confidence_report.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import get_engine
from data_quality_report import generar_candidatos_foneticos

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    sys.exit("ERROR: define DATABASE_URL (ver .env.example)")

_SOLO_DIGITOS_RE = re.compile(r"[^0-9]")


def normalizar_cedula(cedula: str | None) -> str | None:
    """Igual criterio que scrape_target_cedulas.py: solo dígitos, 6-9 de largo."""
    if not cedula:
        return None
    digitos = _SOLO_DIGITOS_RE.sub("", cedula)
    if 6 <= len(digitos) <= 9:
        return digitos
    return None


def clasificar_confianza(score, edad_a, edad_b, ced_a, ced_b) -> str:
    ced_a_norm = normalizar_cedula(ced_a)
    ced_b_norm = normalizar_cedula(ced_b)
    if ced_a_norm and ced_b_norm and ced_a_norm == ced_b_norm:
        return "ALTA"
    if score == 1.0 and edad_a and edad_b:
        try:
            if int(edad_a) == int(edad_b):
                return "MEDIA"
        except ValueError:
            pass
    return "BAJA"


class UnionFind:
    def __init__(self):
        self.padre: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.padre.setdefault(x, x)
        while self.padre[x] != x:
            self.padre[x] = self.padre[self.padre[x]]
            x = self.padre[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.padre[ra] = rb


def main():
    engine = get_engine(DATABASE_URL)
    with Session(engine) as session:
        total_personas = session.execute(
            text("SELECT COUNT(*) FROM personas WHERE nombre IS NOT NULL AND nombre != ''")
        ).scalar()

        print("Generando candidatos fonéticos (mismo algoritmo que data_quality_report.py sección 4)...")
        candidatos = generar_candidatos_foneticos(session)
        print(f"\nTotal personas: {total_personas}")
        print(f"Total candidatos a duplicado: {len(candidatos)}")

        por_tier: dict[str, list] = {"ALTA": [], "MEDIA": [], "BAJA": []}
        uf = UnionFind()
        for score, id_a, nom_a, id_b, nom_b, edad_a, edad_b, hosp_a, hosp_b, ced_a, ced_b in candidatos:
            tier = clasificar_confianza(score, edad_a, edad_b, ced_a, ced_b)
            por_tier[tier].append((score, id_a, nom_a, id_b, nom_b, edad_a, edad_b, ced_a, ced_b))
            if tier == "ALTA":
                uf.union(id_a, id_b)

        print("\n=== Distribución por nivel de confianza ===")
        for tier in ("ALTA", "MEDIA", "BAJA"):
            print(f"  {tier}: {len(por_tier[tier])}")

        print("\n--- Muestra ALTA (misma cédula, score fonético) ---")
        for score, id_a, nom_a, id_b, nom_b, edad_a, edad_b, ced_a, ced_b in por_tier["ALTA"][:15]:
            print(f"  score={score}")
            print(f"    A: id={id_a} nombre='{nom_a}' edad={edad_a} cedula='{ced_a}'")
            print(f"    B: id={id_b} nombre='{nom_b}' edad={edad_b} cedula='{ced_b}'")

        print("\n--- Muestra MEDIA (score=1.0, edad idéntica, sin cédula en común) ---")
        for score, id_a, nom_a, id_b, nom_b, edad_a, edad_b, ced_a, ced_b in por_tier["MEDIA"][:10]:
            print(f"  score={score}")
            print(f"    A: id={id_a} nombre='{nom_a}' edad={edad_a}")
            print(f"    B: id={id_b} nombre='{nom_b}' edad={edad_b}")

        # Estimación de personas únicas: cada persona en algún cluster ALTA
        # cuenta una vez por cluster; el resto (no involucradas en ningún
        # match ALTA) cuentan cada una individualmente.
        ids_en_alta = set(uf.padre.keys())
        clusters_alta = len({uf.find(x) for x in ids_en_alta})
        personas_fuera_de_alta = total_personas - len(ids_en_alta)
        estimado_unico = clusters_alta + personas_fuera_de_alta

        print("\n=== Estimación de personas únicas tras fusionar solo el tier ALTA ===")
        print(f"  Personas involucradas en al menos un match ALTA: {len(ids_en_alta)}")
        print(f"  Esas se agrupan en: {clusters_alta} clusters (personas únicas)")
        print(f"  Personas sin ningún match ALTA (cuentan individualmente): {personas_fuera_de_alta}")
        print(f"  TOTAL estimado de personas únicas (cota superior conservadora): {estimado_unico}")
        print(f"  (de {total_personas} filas totales — una fusión también del tier MEDIA bajaría más este número,")
        print(f"   pero con más riesgo de fusionar por error a dos personas distintas)")


if __name__ == "__main__":
    main()
